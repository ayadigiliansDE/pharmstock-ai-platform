from __future__ import annotations

import json
from pathlib import Path

import pytest

from pharmstock.rebuild.bigquery_stage import (
    BIGQUERY_REBUILD_DATASET,
    STAGE7H_GOLD_MODELS,
    STAGE7H_INTERMEDIATE_MODELS,
    STAGE7H_STAGING_MODELS,
    TABLE_LAYOUTS,
    Stage7HConfig,
    atomic_replace_sql,
    build_preflight,
    duplicate_primary_key_sql,
    load_stage7g_plan,
    stage7h_contract,
)
from pharmstock.rebuild.contracts import SNAPSHOT_TABLES
from scripts.run_checkpoint import checkpoint_command

ROOT = Path(__file__).resolve().parents[1]
CLOUD_RUNNER = ROOT / "scripts/run_stage7h_cloud.py"
CHECKPOINT = ROOT / "scripts/run_stage7h_checkpoint.py"
DBT_ROOT = ROOT / "dbt/pharmstock_analytics"
DOC = ROOT / "docs/STAGE_07H_BIGQUERY_DBT_DEPLOYMENT.md"


def _fake_stage7g(root: Path) -> None:
    root.mkdir(parents=True)
    tables = []
    total = 0
    for index, spec in enumerate(SNAPSHOT_TABLES, start=1):
        local = root / "parquet" / spec.schema_name / spec.table_name
        local.mkdir(parents=True)
        (local / "part-00000.parquet").write_bytes(b"PAR1")
        rows = index
        total += rows
        tables.append(
            {
                "source_table": spec.source_table,
                "target_table": f"{BIGQUERY_REBUILD_DATASET}.{spec.bigquery_table}",
                "local_parquet_path": str(local),
                "rows": rows,
                "primary_key": list(spec.primary_key),
                "source_layer": "historical_snapshot",
                "write_strategy": "STAGING_THEN_ATOMIC_REPLACE",
            }
        )
    (root / "bigquery_rebuild_plan.json").write_text(
        json.dumps({"stage": "7G", "snapshot_tables": tables}), encoding="utf-8"
    )
    (root / "rebuild_verification.json").write_text(
        json.dumps(
            {
                "stage": "7G",
                "status": "PASS",
                "bigquery_ready": True,
                "snapshot_total_rows": total,
            }
        ),
        encoding="utf-8",
    )
    (root / "_SUCCESS").write_text("PASS\n", encoding="utf-8")


def test_stage7h_covers_all_stage7g_tables_with_physical_layouts() -> None:
    assert len(TABLE_LAYOUTS) == len(SNAPSHOT_TABLES) == 26
    assert set(TABLE_LAYOUTS) == {spec.source_table for spec in SNAPSHOT_TABLES}
    assert TABLE_LAYOUTS["pos.sale_header"].partition_expression == "DATE(transaction_ts)"
    assert "branch_id" in TABLE_LAYOUTS["inventory.stock_movement"].clustering_fields


def test_stage7h_contract_is_explicit_cloud_boundary() -> None:
    contract = stage7h_contract()
    assert contract["raw_dataset"] == "pharmstock_ops_rebuild"
    assert contract["raw_table_count"] == 26
    assert contract["safety"]["checkpoint_cloud_mutation"] is False
    assert contract["safety"]["cloud_execution_requires_execute"] is True
    assert contract["safety"]["cloud_execution_requires_replace"] is True
    assert contract["safety"]["validate_primary_keys"] is True


def test_stage7h_atomic_replace_has_partitioning_and_clustering() -> None:
    sql = atomic_replace_sql(
        target_table_id="p.d.pos__sale_header",
        staging_table_id="p.d.__stage",
        source_table="pos.sale_header",
    )
    assert "CREATE OR REPLACE TABLE `p.d.pos__sale_header`" in sql
    assert "PARTITION BY DATE(transaction_ts)" in sql
    assert "CLUSTER BY `branch_id`, `channel`, `transaction_status`" in sql
    assert "AS SELECT * FROM `p.d.__stage`" in sql


def test_stage7h_duplicate_pk_query_supports_composite_keys() -> None:
    sql = duplicate_primary_key_sql("p.d.inventory", ("branch_id", "product_id"))
    assert "GROUP BY `branch_id`, `product_id`" in sql
    assert "HAVING c > 1" in sql
    with pytest.raises(ValueError, match="primary key"):
        duplicate_primary_key_sql("p.d.x", ())


def test_stage7h_plan_rejects_primary_key_drift(tmp_path: Path) -> None:
    root = tmp_path / "stage7g"
    _fake_stage7g(root)
    plan_path = root / "bigquery_rebuild_plan.json"
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    payload["snapshot_tables"][0]["primary_key"] = ["wrong"]
    plan_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="primary key drift"):
        load_stage7g_plan(plan_path)


def test_stage7h_preflight_reconciles_26_table_row_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage7g = tmp_path / "stage7g"
    _fake_stage7g(stage7g)
    monkeypatch.chdir(ROOT)
    preflight = build_preflight(
        config=Stage7HConfig("project", "pharmstock_ops_rebuild", "EU", "pharmstock"),
        stage7g_root=stage7g,
    )
    assert preflight["snapshot_table_count"] == 26
    assert preflight["expected_snapshot_rows"] == sum(range(1, 27))
    assert preflight["local_ready"] is True
    assert preflight["cloud_mutation"] is False


def test_stage7h_dbt_model_sets_are_complete() -> None:
    assert len(STAGE7H_STAGING_MODELS) == 11
    assert len(STAGE7H_INTERMEDIATE_MODELS) == 4
    assert len(STAGE7H_GOLD_MODELS) == 3
    for name in STAGE7H_STAGING_MODELS:
        assert (DBT_ROOT / "models/rebuild_staging" / f"{name}.sql").is_file()
    for name in STAGE7H_INTERMEDIATE_MODELS:
        assert (DBT_ROOT / "models/rebuild_intermediate" / f"{name}.sql").is_file()
    for name in STAGE7H_GOLD_MODELS:
        assert (DBT_ROOT / "models/rebuild_marts" / f"{name}.sql").is_file()


def test_stage7h_cloud_runner_guards_mutation_and_runs_dbt() -> None:
    text = CLOUD_RUNNER.read_text(encoding="utf-8")
    assert 'parser.add_argument("--execute", action="store_true")' in text
    assert 'parser.add_argument("--replace", action="store_true")' in text
    assert 'if not args.replace:' in text
    assert '"build", "--select", "tag:stage7h", "--fail-fast"' in text
    assert "STAGE_7H_STATUS=PASS" in text


def test_stage7h_checkpoint_is_local_safe() -> None:
    text = CHECKPOINT.read_text(encoding="utf-8")
    assert "LOCAL SAFE PREFLIGHT" in text
    assert "Cloud mutation:                NO" in text
    assert "STAGE_7H_PREFLIGHT_STATUS=PASS" in text


def test_checkpoint_launcher_knows_stage7h() -> None:
    command = checkpoint_command("7h")
    assert command[-1] == "scripts/run_stage7h_checkpoint.py"


def test_stage7h_docs_explain_cloud_guard_and_dbt_layers() -> None:
    text = DOC.read_text(encoding="utf-8")
    assert "26" in text
    assert "no cloud mutation" in text.lower()
    assert "--execute" in text
    assert "--replace" in text
    assert "rebuild_staging" in text
    assert "rebuild_marts" in text
