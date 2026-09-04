from __future__ import annotations

import json
from pathlib import Path

from pharmstock.analytics.powerbi_stage import (
    FORBIDDEN_MONETARY_TERMS,
    MEASURE_NAMES,
    PBI_MODEL_FILES,
    PBI_TABLE_ALIASES,
    RELATIONSHIPS,
    connection_template,
    dax_measure_library,
    inspect_stage6a,
    semantic_model_contract,
    write_stage6a_local_artifacts,
)


def test_stage6a_has_eleven_serving_models() -> None:
    assert len(PBI_MODEL_FILES) == 11
    assert len(PBI_TABLE_ALIASES) == 11
    assert set(PBI_MODEL_FILES) == set(PBI_TABLE_ALIASES)


def test_serving_aliases_expose_clean_powerbi_names() -> None:
    assert PBI_TABLE_ALIASES["pbi_dim_date"] == "dim_date"
    assert PBI_TABLE_ALIASES["pbi_fact_sales_demand"] == "fact_sales_demand"
    assert PBI_TABLE_ALIASES["pbi_mart_branch_daily_operations"] == (
        "mart_branch_daily_operations"
    )


def test_semantic_contract_uses_import_and_adbc_v2() -> None:
    contract = semantic_model_contract("project-x", "pharmstock_pbi")
    connector = contract["connector"]
    assert connector["implementation"] == "2.0"
    assert connector["driver_family"] == "ADBC"
    assert connector["recommended_initial_storage_mode"] == "Import"
    assert all(table["storage_mode"] == "Import" for table in contract["tables"])


def test_semantic_contract_has_single_direction_one_to_many_relationships() -> None:
    contract = semantic_model_contract("project-x", "pharmstock_pbi")
    relationships = contract["relationships"]
    assert len(relationships) == 17
    assert all(item["cardinality"] == "one_to_many" for item in relationships)
    assert all(item["cross_filter_direction"] == "single" for item in relationships)


def test_relationships_cover_four_dimensions() -> None:
    dimensions = {relationship[0] for relationship in RELATIONSHIPS}
    assert dimensions == {"dim_date", "dim_product", "dim_branch", "dim_supplier"}


def test_measure_library_is_explicit_and_non_monetary() -> None:
    dax = dax_measure_library()
    assert len(MEASURE_NAMES) == 18
    for name in MEASURE_NAMES:
        assert f"{name} :=" in dax
    lower = dax.lower()
    for term in FORBIDDEN_MONETARY_TERMS:
        assert term not in lower


def test_connection_template_sets_billing_project_and_adbc() -> None:
    text = connection_template("project-x")
    assert 'BillingProject = "project-x"' in text
    assert 'Implementation = "2.0"' in text
    assert "GoogleBigQuery.Database" in text


def test_local_artifacts_are_cloud_safe(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "dbt/pharmstock_analytics/models/powerbi_serving"
    project.mkdir(parents=True)
    for model in PBI_MODEL_FILES:
        (project / f"{model}.sql").write_text("select 1\n", encoding="utf-8")
    stage5d = tmp_path / "artifacts/stage5d"
    stage5d.mkdir(parents=True)
    (stage5d / "dimensions_execution_report.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PHARMSTOCK_BQ_PROJECT", "project-x")
    report = write_stage6a_local_artifacts(tmp_path / "artifacts/stage6a")
    assert report["cloud_mutation"] is False
    assert report["monetary_measures_generated"] is False
    assert (tmp_path / "artifacts/stage6a/semantic_model_contract.json").is_file()
    assert (tmp_path / "artifacts/stage6a/measures.dax").is_file()


def test_stage6a_inspection_requires_stage5d_dimensions(tmp_path: Path, monkeypatch) -> None:
    serving = tmp_path / "dbt/pharmstock_analytics/models/powerbi_serving"
    serving.mkdir(parents=True)
    for model in PBI_MODEL_FILES:
        (serving / f"{model}.sql").write_text("select 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    readiness = inspect_stage6a()
    assert readiness.project_files_ready is True
    assert readiness.stage5d_dimensions_report_present is False


def test_powerbi_dbt_folder_contains_expected_models() -> None:
    root = Path("dbt/pharmstock_analytics/models/powerbi_serving")
    actual = {path.stem for path in root.glob("*.sql")}
    assert actual == set(PBI_MODEL_FILES)


def test_date_dimension_is_generated_from_operational_dates() -> None:
    sql = Path(
        "dbt/pharmstock_analytics/models/powerbi_serving/pbi_dim_date.sql"
    ).read_text(encoding="utf-8")
    assert "generate_date_array" in sql.lower()
    assert "fct_daily_sales_demand" in sql
    assert "fct_procurement_order_lifecycle" in sql


def test_powerbi_serving_folder_is_view_materialized() -> None:
    project = Path("dbt/pharmstock_analytics/dbt_project.yml").read_text(encoding="utf-8")
    assert "powerbi_serving:" in project
    assert "+materialized: view" in project
    assert "+schema: pbi" in project
    assert '"stage6a"' in project


def test_static_powerbi_assets_match_contract() -> None:
    dax = Path("powerbi/measures.dax").read_text(encoding="utf-8")
    m = Path("powerbi/bigquery_connection.template.m").read_text(encoding="utf-8")
    assert "Fulfillment Rate :=" in dax
    assert "Procurement Fill Rate :=" in dax
    assert 'Implementation = "2.0"' in m
    assert "YOUR_PROJECT_ID" in m


def test_semantic_contract_truth_boundary_is_explicit() -> None:
    contract = semantic_model_contract("p", "d")
    boundary = contract["truth_boundary"]
    assert boundary["product_catalog"] == "official_openFDA_NDC_US_reference"
    assert boundary["pharmacy_network"] == "synthetic_Egypt"
    assert boundary["supplier_network"] == "synthetic"
    assert boundary["authoritative_monetary_data"] is False


def test_generated_contract_json_is_serializable() -> None:
    payload = semantic_model_contract("p", "d")
    loaded = json.loads(json.dumps(payload))
    assert loaded["dataset_id"] == "d"
    assert len(loaded["tables"]) == 11


def test_stage6a_deployment_enforces_dbt_dataset_naming_contract() -> None:
    script = Path("scripts/run_stage6a_powerbi.py").read_text(encoding="utf-8")
    assert 'expected_pbi_dataset = f"{args.base_dataset}_pbi"' in script
    assert "dbt schema contract requires --pbi-dataset" in script
