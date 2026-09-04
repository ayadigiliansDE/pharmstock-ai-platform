from __future__ import annotations

import csv
import json
from pathlib import Path

from pharmstock.analytics.powerbi_desktop_stage import (
    MEASURE_METADATA,
    POWERBI_DESKTOP_FILE_NAME,
    REPORT_PAGE_NAMES,
    dashboard_spec,
    desktop_build_manifest,
    inspect_stage6b,
    write_stage6b_build_kit,
)


def test_stage6b_manifest_matches_stage6a_contract_counts() -> None:
    manifest = desktop_build_manifest("project-x", "pharmstock_pbi")
    assert len(manifest["tables"]) == 11
    assert len(manifest["relationships"]) == 17
    assert len(manifest["measures"]) == 18
    assert manifest["storage_mode"] == "Import"


def test_stage6b_requires_date_table_configuration() -> None:
    date_table = desktop_build_manifest("p")["date_table"]
    assert date_table["table"] == "dim_date"
    assert date_table["date_column"] == "date"
    assert date_table["sort_columns"]["month_name"] == "month_number"
    assert date_table["sort_columns"]["day_name"] == "day_of_week_number"


def test_measure_metadata_covers_all_measures_and_formats_rates() -> None:
    manifest = desktop_build_manifest("p")
    names = {item["name"] for item in manifest["measures"]}
    assert names == set(MEASURE_METADATA)
    assert MEASURE_METADATA["Fulfillment Rate"][1] == "0.0%"
    assert MEASURE_METADATA["Procurement Fill Rate"][1] == "0.0%"


def test_report_spec_has_three_operational_pages() -> None:
    spec = dashboard_spec()
    names = tuple(page["name"] for page in spec["pages"])
    assert names == REPORT_PAGE_NAMES
    assert spec["truth_boundary"]["authoritative_monetary_data"] is False


def test_operations_overview_has_six_kpis_and_core_trend() -> None:
    page = dashboard_spec()["pages"][0]
    cards = [item for item in page["visuals"] if item["type"] == "card"]
    assert len(cards) == 6
    assert any(item["type"] == "line_chart" for item in page["visuals"])


def test_build_kit_writes_all_desktop_assets(tmp_path: Path, monkeypatch) -> None:
    stage6a = tmp_path / "artifacts/stage6a"
    stage6a.mkdir(parents=True)
    (stage6a / "_CLOUD_SUCCESS").write_text("PASS\n", encoding="utf-8")
    powerbi = tmp_path / "powerbi"
    powerbi.mkdir()
    (powerbi / "semantic_model_contract.template.json").write_text("{}\n", encoding="utf-8")
    (powerbi / "measures.dax").write_text("x\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    report = write_stage6b_build_kit(
        tmp_path / "artifacts/stage6b",
        project_id="project-x",
        dataset_id="pharmstock_pbi",
    )
    assert report["build_kit_ready"] is True
    assert report["stage6b_pass_claimed"] is False
    for name in (
        "desktop_build_manifest.json",
        "relationships.csv",
        "measures.csv",
        "measures.dax",
        "dashboard_spec.json",
        "bigquery_connection.m",
        "desktop_acceptance_checklist.md",
        "build_kit_verification.json",
    ):
        assert (tmp_path / "artifacts/stage6b" / name).is_file()


def test_relationship_csv_has_seventeen_active_single_direction_rows(
    tmp_path: Path, monkeypatch
) -> None:
    stage6a = tmp_path / "artifacts/stage6a"
    stage6a.mkdir(parents=True)
    (stage6a / "_CLOUD_SUCCESS").write_text("PASS\n", encoding="utf-8")
    powerbi = tmp_path / "powerbi"
    powerbi.mkdir()
    (powerbi / "semantic_model_contract.template.json").write_text("{}\n", encoding="utf-8")
    (powerbi / "measures.dax").write_text("x\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "artifacts/stage6b"
    write_stage6b_build_kit(out, project_id="p")
    with (out / "relationships.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 17
    assert all(row["cardinality"] == "1:*" for row in rows)
    assert all(row["cross_filter"] == "Single" for row in rows)
    assert all(row["active"] == "YES" for row in rows)


def test_acceptance_does_not_claim_desktop_pass_automatically() -> None:
    acceptance = desktop_build_manifest("p")["acceptance"]
    assert acceptance["loaded_tables"] == 11
    assert acceptance["active_relationships"] == 17
    assert acceptance["explicit_measures"] == 18
    assert acceptance["refresh_required"] is True
    assert POWERBI_DESKTOP_FILE_NAME.endswith(".pbix")


def test_stage6b_readiness_requires_stage6a_cloud_marker(tmp_path: Path, monkeypatch) -> None:
    powerbi = tmp_path / "powerbi"
    powerbi.mkdir()
    (powerbi / "semantic_model_contract.template.json").write_text("{}\n", encoding="utf-8")
    (powerbi / "measures.dax").write_text("x\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    readiness = inspect_stage6b()
    assert readiness.stage6a_cloud_success is False
    assert readiness.semantic_contract_present is True
    assert readiness.measure_library_present is True


def test_dashboard_spec_is_json_serializable() -> None:
    loaded = json.loads(json.dumps(dashboard_spec()))
    assert loaded["stage"] == "6B"
    assert len(loaded["pages"]) == 3


def test_dashboard_spec_uses_real_dimension_columns() -> None:
    text = json.dumps(dashboard_spec())
    assert "dim_branch[governorate]" in text
    assert "dim_branch[pharmacy_type]" in text
    assert "dim_product[display_name]" in text
    assert "governorate_name_en" not in text
    assert "branch_type" not in text
