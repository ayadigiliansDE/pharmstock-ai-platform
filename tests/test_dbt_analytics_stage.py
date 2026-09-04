import json
from pathlib import Path

from pharmstock.analytics.dbt_stage import (
    FORBIDDEN_MONETARY_TOKENS,
    GOLD_MODELS,
    INTERMEDIATE_MODELS,
    STAGING_MODELS,
    DbtStage5CConfig,
    build_analytics_catalog,
    inspect_stage5c_project,
)


def test_stage5c_model_contract_counts() -> None:
    assert len(STAGING_MODELS) == 7
    assert len(INTERMEDIATE_MODELS) == 3
    assert len(GOLD_MODELS) == 7


def test_stage5c_project_files_exist() -> None:
    root = Path("dbt/pharmstock_analytics")
    assert (root / "dbt_project.yml").is_file()
    assert Path("dbt/profiles/profiles.yml").is_file()
    assert (root / "models/staging/_sources.yml").is_file()
    assert (root / "models/marts/_marts.yml").is_file()


def test_stage5c_profile_uses_oauth_and_environment() -> None:
    profile = Path("dbt/profiles/profiles.yml").read_text(encoding="utf-8")
    assert "method: oauth" in profile
    assert "PHARMSTOCK_BQ_PROJECT" in profile
    assert "PHARMSTOCK_DBT_BASE_DATASET" in profile
    assert "PHARMSTOCK_BQ_LOCATION" in profile


def test_stage5c_sources_point_to_silver_environment_dataset() -> None:
    source = Path("dbt/pharmstock_analytics/models/staging/_sources.yml").read_text(
        encoding="utf-8"
    )
    assert "PHARMSTOCK_BQ_SOURCE_DATASET" in source
    assert "pharmstock_silver" in source
    for name in (
        "event_index",
        "sales_units_fulfilled",
        "inventory_quantity_changed",
        "inventory_reorder_required",
        "purchase_order_created",
        "goods_receipt_received",
        "restock_applied",
    ):
        assert f"name: {name}" in source


def test_stage5c_materialization_strategy_is_layered() -> None:
    project = Path("dbt/pharmstock_analytics/dbt_project.yml").read_text(encoding="utf-8")
    assert "+materialized: view" in project
    assert "+materialized: ephemeral" in project
    assert "+materialized: table" in project
    assert "+schema: stg" in project
    assert "+schema: gold" in project


def test_stage5c_gold_models_have_no_fabricated_monetary_columns() -> None:
    root = Path("dbt/pharmstock_analytics/models/marts")
    sql = "\n".join(path.read_text(encoding="utf-8").lower() for path in root.glob("*.sql"))
    for token in FORBIDDEN_MONETARY_TOKENS:
        assert token not in sql


def test_stage5c_procurement_explicitly_preserves_non_monetary_flag() -> None:
    sql = Path(
        "dbt/pharmstock_analytics/models/intermediate/int_procurement_order_lifecycle.sql"
    ).read_text(encoding="utf-8")
    test_sql = Path(
        "dbt/pharmstock_analytics/tests/assert_procurement_non_monetary.sql"
    ).read_text(encoding="utf-8")
    assert "monetary_values_generated" in sql
    assert "where monetary_values_generated" in test_sql


def test_stage5c_has_at_least_nine_singular_data_tests() -> None:
    tests = tuple(Path("dbt/pharmstock_analytics/tests").glob("*.sql"))
    assert len(tests) >= 9


def test_stage5c_gold_partition_and_cluster_configs_present() -> None:
    partitioned = (
        "fct_daily_sales_demand",
        "fct_daily_inventory_movement",
        "fct_reorder_events",
        "fct_procurement_order_lifecycle",
        "mart_branch_daily_operations",
        "mart_product_daily_demand",
    )
    root = Path("dbt/pharmstock_analytics/models/marts")
    for name in partitioned:
        text = (root / f"{name}.sql").read_text(encoding="utf-8")
        assert "partition_by=" in text
        assert "cluster_by=" in text


def test_stage5c_exposes_powerbi_lineage() -> None:
    schema = Path("dbt/pharmstock_analytics/models/marts/_marts.yml").read_text(
        encoding="utf-8"
    )
    assert "powerbi_pharmstock_operations" in schema
    assert "type: dashboard" in schema
    assert "mart_branch_daily_operations" in schema


def test_stage5c_catalog_marks_master_dimensions_incomplete() -> None:
    config = DbtStage5CConfig("project-id", "pharmstock_silver", "pharmstock", "EU")
    catalog = build_analytics_catalog(config)
    assert catalog["gold_dataset"] == "pharmstock_gold"
    assert catalog["staging_dataset"] == "pharmstock_stg"
    assert catalog["monetary_measures_generated"] is False
    assert catalog["master_dimensions_complete"] is False


def test_stage5c_local_readiness_with_dbt_and_cloud_report(tmp_path: Path) -> None:
    stage5b = tmp_path / "stage5b"
    stage5b.mkdir()
    (stage5b / "cloud_execution_report.json").write_text(
        json.dumps({"cloud_mutation": True}), encoding="utf-8"
    )
    readiness = inspect_stage5c_project(
        Path("dbt/pharmstock_analytics"),
        stage5b,
        installed=True,
        config=DbtStage5CConfig(
            "pharmstock-ai-platform-2026", "pharmstock_silver", "pharmstock", "EU"
        ),
    )
    assert readiness.project_files_ready is True
    assert readiness.local_ready is True
    assert readiness.cloud_ready_hint is True
    assert readiness.gold_model_count == 7


def test_stage5c_runner_is_dry_run_by_default_and_execute_is_explicit() -> None:
    source = Path("scripts/run_stage5c_dbt.py").read_text(encoding="utf-8")
    assert 'parser.add_argument("--execute", action="store_true")' in source
    assert "STAGE_5C_DBT_MODE=DRY_RUN" in source
    assert "Cloud mutation:   NO / DRY RUN" in source
    assert '[_dbt' not in source


def test_stage5c_cloud_runner_validates_stage5b_then_builds_and_verifies() -> None:
    source = Path("scripts/run_stage5c_dbt.py").read_text(encoding="utf-8")
    assert "_validate_stage5b_report(args)" in source
    assert '["debug"]' in source
    assert '["build", "--fail-fast"]' in source
    assert '["docs", "generate"]' in source
    assert "STAGE_5C_CLOUD_STATUS=PASS" in source
    assert "_verify_gold(args)" in source


def test_stage5c_checkpoint_is_registered() -> None:
    source = Path("scripts/run_checkpoint.py").read_text(encoding="utf-8")
    assert 'if checkpoint == "5c":' in source
    assert '"scripts/run_stage5c_checkpoint.py"' in source
    assert '"5c"' in source


def test_stage5c_optional_dependency_is_pinned() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'dbt-core==1.12.2' in pyproject
    assert 'dbt-bigquery==1.12.0' in pyproject
