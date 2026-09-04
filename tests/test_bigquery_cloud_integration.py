import json
from pathlib import Path

from pharmstock.warehouse.bigquery_cloud import (
    BigQueryCloudConfig,
    assess_bigquery_readiness,
    discover_local_warehouse,
    write_stage5b_local_plan,
)
from pharmstock.warehouse.bigquery_contracts import TABLE_CONTRACTS


def _fake_stage5a(root: Path) -> Path:
    stage5a = root / "stage5a"
    (stage5a / "warehouse_ready").mkdir(parents=True)
    tables = {}
    for index, name in enumerate(TABLE_CONTRACTS, start=1):
        table_root = stage5a / "warehouse_ready" / name
        table_root.mkdir(parents=True)
        (table_root / "part-00000.parquet").write_bytes(b"PAR1fake")
        tables[name] = {"exported_rows": index}
    (stage5a / "spark_export_summary.json").write_text(
        json.dumps({"tables": tables}), encoding="utf-8"
    )
    (stage5a / "_SUCCESS").write_text("ok\n", encoding="utf-8")
    return stage5a


def test_stage5b_discovers_all_bigquery_ready_tables(tmp_path: Path) -> None:
    stage5a = _fake_stage5a(tmp_path)
    tables = discover_local_warehouse(stage5a)

    assert len(tables) == 7
    assert {table.table_name for table in tables} == set(TABLE_CONTRACTS)
    assert sum(table.expected_rows for table in tables) == sum(range(1, 8))


def test_stage5b_readiness_does_not_require_cloud_client_for_local_pass(tmp_path: Path) -> None:
    stage5a = _fake_stage5a(tmp_path)
    config = BigQueryCloudConfig(None, "pharmstock_silver", "EU")

    readiness = assess_bigquery_readiness(
        stage5a, config, client_installed=False, credential_hint_present=False
    )

    assert readiness.local_ready is True
    assert readiness.cloud_preconditions_present is False
    assert readiness.table_count == 7
    assert "PHARMSTOCK_BQ_PROJECT is not configured" in readiness.issues


def test_stage5b_cloud_ready_requires_client_project_and_valid_dataset(tmp_path: Path) -> None:
    stage5a = _fake_stage5a(tmp_path)
    config = BigQueryCloudConfig("my-gcp-project", "pharmstock_silver", "EU")

    readiness = assess_bigquery_readiness(
        stage5a, config, client_installed=True, credential_hint_present=True
    )

    assert readiness.cloud_preconditions_present is True
    assert readiness.issues == ()


def test_stage5b_rejects_invalid_dataset_id(tmp_path: Path) -> None:
    stage5a = _fake_stage5a(tmp_path)
    config = BigQueryCloudConfig("my-gcp-project", "bad-dataset-id", "EU")

    readiness = assess_bigquery_readiness(
        stage5a, config, client_installed=True, credential_hint_present=True
    )

    assert readiness.dataset_id_valid is False
    assert readiness.cloud_preconditions_present is False


def test_stage5b_writes_safe_local_deployment_plan(tmp_path: Path) -> None:
    stage5a = _fake_stage5a(tmp_path)
    output = tmp_path / "stage5b"
    config = BigQueryCloudConfig(None, "pharmstock_silver", "EU")

    plan = write_stage5b_local_plan(output, stage5a, config)

    assert plan["cloud_mutation"] is False
    assert plan["deployment_strategy"]["promotion"] == (
        "CREATE OR REPLACE target with explicit NOT NULL contract from verified staging"
    )
    assert (output / "cloud_readiness.json").exists()
    assert (output / "deployment_plan.json").exists()


def test_bigquery_cloud_module_has_no_google_import_at_module_scope() -> None:
    source = Path("src/pharmstock/warehouse/bigquery_cloud.py").read_text(encoding="utf-8")

    assert "from google.cloud" not in source
    assert "import google.auth" not in source


def test_stage5b_live_loader_uses_adc_staging_and_atomic_promotion() -> None:
    source = Path("scripts/run_stage5b_bigquery.py").read_text(encoding="utf-8")

    assert "google.auth.default(" in source
    assert "load_table_from_file(" in source
    assert "CREATE OR REPLACE TABLE" in source
    assert "staging contains NULL in REQUIRED fields" in source
    assert "relax_required=staging" in source
    assert "__stage5b_" in source
    assert "client.delete_table(staging_id, not_found_ok=True)" in source


def test_stage5b_live_loader_requires_execute_replace_and_project() -> None:
    source = Path("scripts/run_stage5b_bigquery.py").read_text(encoding="utf-8")

    assert 'parser.add_argument("--execute", action="store_true")' in source
    assert 'parser.add_argument("--replace", action="store_true")' in source
    assert "Cloud execution requires --replace" in source
    assert "Set --project or PHARMSTOCK_BQ_PROJECT" in source


def test_stage5b_checkpoint_is_registered() -> None:
    source = Path("scripts/run_checkpoint.py").read_text(encoding="utf-8")

    assert 'if checkpoint == "5b":' in source
    assert '"scripts/run_stage5b_checkpoint.py"' in source


def test_stage5b_allows_zero_row_table_without_parquet_part(tmp_path: Path) -> None:
    stage5a = _fake_stage5a(tmp_path)
    summary_path = stage5a / "spark_export_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["tables"]["inventory_reorder_required"]["exported_rows"] = 0
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    for path in (stage5a / "warehouse_ready" / "inventory_reorder_required").glob("*.parquet"):
        path.unlink()

    tables = {table.table_name: table for table in discover_local_warehouse(stage5a)}

    assert tables["inventory_reorder_required"].expected_rows == 0
    assert tables["inventory_reorder_required"].parquet_files == ()


def test_stage5b_hotfix_relaxes_only_staging_required_modes() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "stage5b_loader", Path("scripts/run_stage5b_bigquery.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class SchemaField:
        def __init__(self, name, field_type, *, mode, description):
            self.name = name
            self.field_type = field_type
            self.mode = mode
            self.description = description

    class FakeBigQuery:
        pass

    FakeBigQuery.SchemaField = SchemaField
    contract = TABLE_CONTRACTS["event_index"]
    target = module._schema_fields(FakeBigQuery, contract)
    staging = module._schema_fields(FakeBigQuery, contract, relax_required=True)

    assert next(field for field in target if field.name == "event_id").mode == "REQUIRED"
    assert next(field for field in staging if field.name == "event_id").mode == "NULLABLE"
    assert next(field for field in staging if field.name == "correlation_id").mode == "NULLABLE"


def test_stage5b_hotfix_promotion_ddl_preserves_required_contract() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "stage5b_loader_sql", Path("scripts/run_stage5b_bigquery.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    sql = module._promotion_sql(
        staging_id="p.d.__stage5b_event_index_x",
        target_id="p.d.event_index",
        contract=TABLE_CONTRACTS["event_index"],
    )

    assert "`event_id` STRING NOT NULL" in sql
    assert "`correlation_id` STRING NOT NULL" not in sql
    assert "PARTITION BY `event_date`" in sql
    assert "CLUSTER BY `event_type`, `aggregate_type`, `aggregate_id`" in sql
    assert "FROM `p.d.__stage5b_event_index_x`" in sql
