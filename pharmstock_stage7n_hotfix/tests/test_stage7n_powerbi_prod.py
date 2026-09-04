from __future__ import annotations

import json
from pathlib import Path

from pharmstock.analytics.powerbi_prod_stage import (
    BIGQUERY_VIEWS,
    DEFAULT_PBI_PROD_DATASET,
    MEASURES,
    POSTGRES_VIEWS,
    STAGE7N_VERSION,
    bigquery_view_sql,
    report_spec,
    semantic_contract,
    write_stage7n_artifacts,
)
from scripts.run_checkpoint import checkpoint_command


def test_stage7n_contract_version_and_view_counts() -> None:
    assert STAGE7N_VERSION == "0.38.0"
    assert len(BIGQUERY_VIEWS) == 9
    assert len(POSTGRES_VIEWS) == 5
    assert len(MEASURES) == 24


def test_stage7n_bigquery_dataset_is_production_serving_boundary() -> None:
    assert DEFAULT_PBI_PROD_DATASET == "pharmstock_pbi_prod"
    contract = semantic_contract("project-x")
    assert contract["sources"]["bigquery"]["dataset_id"] == DEFAULT_PBI_PROD_DATASET
    assert contract["sources"]["bigquery"]["recommended_mode"] == "Import"


def test_stage7n_contract_has_bigquery_and_postgres_sources() -> None:
    contract = semantic_contract("project-x")
    sources = contract["sources"]
    assert set(sources) == {"bigquery", "postgresql"}
    assert sources["postgresql"]["database"] == "pharmstock_ops"
    assert sources["postgresql"]["schema"] == "bi"
    assert len(contract["tables"]) == 14


def test_stage7n_truth_boundary_labels_modeled_finance_and_ml() -> None:
    boundary = semantic_contract("p")["truth_boundary"]
    assert boundary["retail_price"] == "PUBLIC_MARKET_EGYPT"
    assert boundary["purchase_cost_and_margin"] == "SYNTHETIC_CALIBRATED_MODELED"
    assert "SYNTHETIC_CALIBRATED_OFFLINE_BACKFILL" in boundary["ml_training_provenance"]


def test_stage7n_governance_is_read_only() -> None:
    governance = semantic_contract("p")["governance"]
    assert governance["database_access"] == "READ_ONLY"
    assert governance["procurement_write"] is False
    assert governance["ml_write"] is False
    assert governance["decision_write"] is False


def test_stage7n_relationships_are_dimension_led() -> None:
    relationships = semantic_contract("p")["relationships"]
    assert len(relationships) == 16
    dimensions = {row[0] for row in relationships}
    assert dimensions == {"dim_date", "dim_branch", "dim_product", "dim_supplier"}


def test_stage7n_bigquery_views_use_rebuild_gold_and_current_state() -> None:
    sql = bigquery_view_sql(project_id="p")
    assert set(sql) == set(BIGQUERY_VIEWS)
    assert "pharmstock_rebuild_gold" in sql["fact_branch_daily_operations"]
    assert "pharmstock_ops_current" in sql["snapshot_inventory_position"]
    assert "inventory__stock_batch" in sql["snapshot_batch_expiry"]
    assert "CURRENT_DATE('Africa/Cairo')" in sql["snapshot_batch_expiry"]


def test_stage7n_bigquery_views_are_metadata_only_contract() -> None:
    runner = Path("scripts/run_stage7n_powerbi.py").read_text(encoding="utf-8")
    assert "view.view_query" in runner
    assert '"bigquery_data_tables_created": 0' in runner
    assert "METADATA_ONLY_BIGQUERY_VIEWS" in runner


def test_stage7n_postgres_bi_role_has_no_write_grants() -> None:
    sql = Path("infra/docker/postgres/sql/012_stage7n_powerbi_readonly.sql").read_text(
        encoding="utf-8"
    )
    assert "CREATE ROLE pharmstock_bi LOGIN" in sql
    assert "GRANT SELECT ON ALL TABLES IN SCHEMA bi TO pharmstock_bi" in sql
    assert "REVOKE CREATE ON SCHEMA bi FROM pharmstock_bi" in sql
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE" in sql
    assert "GRANT INSERT" not in sql
    assert "GRANT UPDATE" not in sql


def test_stage7n_postgres_exposes_ml_and_governed_decisions() -> None:
    sql = Path("infra/docker/postgres/sql/012_stage7n_powerbi_readonly.sql").read_text(
        encoding="utf-8"
    )
    for view in POSTGRES_VIEWS:
        assert f"CREATE OR REPLACE VIEW bi.{view}" in sql
    assert "mlops.latest_branch_product_decision" in sql
    assert "decision_ops.v_case_workbench" in sql
    assert "decision_ops.decision_audit" in sql
    assert "acceptance_smoke" in sql



def test_stage7n_expiry_view_uses_explicit_join_keys() -> None:
    sql = Path("infra/docker/postgres/sql/012_stage7n_powerbi_readonly.sql").read_text(
        encoding="utf-8"
    )
    expiry_sql = sql.split("CREATE OR REPLACE VIEW bi.v_ml_expiry_risk", 1)[1].split(
        "CREATE OR REPLACE VIEW bi.v_decision_case", 1
    )[0]
    assert "JOIN inventory.stock_batch sb\n    ON sb.batch_id = r.batch_id" in expiry_sql
    assert "AND sb.branch_id = r.branch_id" in expiry_sql
    assert "AND sb.product_id = r.product_id" in expiry_sql
    assert "JOIN master.pharmacy_branch b\n    ON b.branch_id = r.branch_id" in expiry_sql
    assert "JOIN master.product p\n    ON p.product_id = r.product_id" in expiry_sql
    assert "USING (branch_id)" not in expiry_sql
    assert "USING (product_id)" not in expiry_sql

def test_stage7n_measure_library_includes_operations_finance_and_ai() -> None:
    names = {name for name, _, _ in MEASURES}
    assert "Fill Rate" in names
    assert "Net Sales EGP" in names
    assert "Modeled Gross Profit EGP" in names
    assert "Below Reorder Positions" in names
    assert "Open Decision Cases" in names
    assert "Decision Acceptance Rate" in names


def test_stage7n_report_spec_has_five_pages() -> None:
    pages = report_spec()["pages"]
    assert [page["name"] for page in pages] == [
        "Executive Operations",
        "Branch & Demand",
        "Inventory & Expiry",
        "Supplier & Procurement",
        "AI & Decision Operations",
    ]


def test_stage7n_artifacts_are_local_and_serializable(tmp_path: Path) -> None:
    report = write_stage7n_artifacts(tmp_path, project_id="project-x")
    assert report["cloud_mutation"] is False
    assert report["bigquery_views"] == 9
    assert report["postgres_views"] == 5
    for name in (
        "semantic_model_contract.json",
        "measures.dax",
        "report_spec.json",
        "bigquery_connection.m",
        "postgres_connection.m",
        "desktop_build_checklist.md",
    ):
        assert (tmp_path / name).is_file()
    contract = json.loads((tmp_path / "semantic_model_contract.json").read_text())
    assert contract["stage"] == "7N"


def test_stage7n_runner_requires_sandbox_for_cloud_execution() -> None:
    runner = Path("scripts/run_stage7n_powerbi.py").read_text(encoding="utf-8")
    assert "PHARMSTOCK_BQ_SANDBOX" in runner
    assert "storage warning" in runner
    assert "STAGE_7N_DRY_RUN_STATUS=PASS" in runner
    assert "STAGE_7N_STATUS=PASS" in runner


def test_stage7n_checkpoint_is_registered() -> None:
    command = checkpoint_command("7n")
    assert command[-1] == "scripts/run_stage7n_powerbi.py"
