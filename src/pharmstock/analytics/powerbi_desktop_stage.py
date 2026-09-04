"""Stage 6B Power BI Desktop semantic-model build-kit helpers."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from pharmstock.analytics.powerbi_stage import (
    DEFAULT_PBI_DATASET,
    FORBIDDEN_MONETARY_TERMS,
    MEASURE_NAMES,
    PBI_TABLE_ALIASES,
    RELATIONSHIPS,
    connection_template,
    dax_measure_library,
    semantic_model_contract,
)

POWERBI_DESKTOP_FILE_NAME = "PharmStock_Operations.pbix"
REPORT_PAGE_NAMES = (
    "Operations Overview",
    "Demand & Stockouts",
    "Inventory & Procurement",
)

MEASURE_METADATA = {
    "Requested Units": ("Demand", "#,0"),
    "Fulfilled Units": ("Demand", "#,0"),
    "Lost Units": ("Demand", "#,0"),
    "Fulfillment Rate": ("Demand", "0.0%"),
    "Demand Lines": ("Demand", "#,0"),
    "Baskets": ("Demand", "#,0"),
    "Inventory Units In": ("Inventory", "#,0"),
    "Inventory Units Out": ("Inventory", "#,0"),
    "Net Quantity Change": ("Inventory", "#,0"),
    "Reorder Events": ("Inventory", "#,0"),
    "Recommended Reorder Units": ("Inventory", "#,0"),
    "Purchase Orders": ("Procurement", "#,0"),
    "Ordered Units": ("Procurement", "#,0"),
    "Received Units": ("Procurement", "#,0"),
    "Procurement Fill Rate": ("Procurement", "0.0%"),
    "Restocked Units": ("Procurement", "#,0"),
    "Active Branches": ("Coverage", "#,0"),
    "Products With Demand": ("Coverage", "#,0"),
}


@dataclass(frozen=True)
class DesktopReadiness:
    stage6a_cloud_success: bool
    semantic_contract_present: bool
    measure_library_present: bool
    table_count: int
    relationship_count: int
    measure_count: int
    report_page_count: int
    desktop_mutation: bool = False


def _overview_page() -> dict[str, object]:
    return {
        "name": "Operations Overview",
        "purpose": "Executive operational health without fabricated monetary metrics.",
        "slicers": [
            "dim_date[date]",
            "dim_branch[governorate]",
            "dim_branch[pharmacy_type]",
        ],
        "visuals": [
            {"type": "card", "measure": "Fulfilled Units"},
            {"type": "card", "measure": "Lost Units"},
            {"type": "card", "measure": "Fulfillment Rate"},
            {"type": "card", "measure": "Active Branches"},
            {"type": "card", "measure": "Products With Demand"},
            {"type": "card", "measure": "Procurement Fill Rate"},
            {
                "type": "line_chart",
                "axis": "dim_date[date]",
                "values": ["Requested Units", "Fulfilled Units", "Lost Units"],
            },
            {
                "type": "bar_chart",
                "axis": "dim_branch[branch_name]",
                "value": "Fulfilled Units",
                "sort": "descending",
            },
            {
                "type": "bar_chart",
                "axis": "dim_product[display_name]",
                "value": "Requested Units",
                "sort": "descending",
                "top_n": 10,
            },
        ],
    }


def _demand_page() -> dict[str, object]:
    return {
        "name": "Demand & Stockouts",
        "slicers": ["dim_date[date]", "dim_branch[governorate]"],
        "visuals": [
            {
                "type": "line_chart",
                "axis": "dim_date[date]",
                "values": ["Requested Units", "Fulfilled Units", "Lost Units"],
            },
            {
                "type": "bar_chart",
                "axis": "dim_product[display_name]",
                "value": "Lost Units",
                "top_n": 15,
            },
            {
                "type": "matrix",
                "rows": ["dim_branch[branch_name]", "dim_product[brand_name]"],
                "values": ["Requested Units", "Fulfilled Units", "Lost Units"],
            },
        ],
    }


def _inventory_page() -> dict[str, object]:
    return {
        "name": "Inventory & Procurement",
        "slicers": ["dim_date[date]", "dim_supplier[supplier_type]"],
        "visuals": [
            {"type": "card", "measure": "Reorder Events"},
            {"type": "card", "measure": "Recommended Reorder Units"},
            {"type": "card", "measure": "Purchase Orders"},
            {"type": "card", "measure": "Procurement Fill Rate"},
            {
                "type": "clustered_column_chart",
                "axis": "dim_date[date]",
                "values": ["Inventory Units In", "Inventory Units Out"],
            },
            {
                "type": "bar_chart",
                "axis": "dim_supplier[supplier_name]",
                "value": "Received Units",
                "sort": "descending",
            },
        ],
    }


def dashboard_spec() -> dict[str, object]:
    """Return the first source-controlled report-page specification."""
    return {
        "stage": "6B",
        "report_name": "PharmStock Operations",
        "pages": [_overview_page(), _demand_page(), _inventory_page()],
        "truth_boundary": {
            "authoritative_monetary_data": False,
            "forbidden_measures": list(FORBIDDEN_MONETARY_TERMS),
        },
    }


def desktop_build_manifest(
    project_id: str,
    dataset_id: str = DEFAULT_PBI_DATASET,
) -> dict[str, object]:
    """Return the deterministic Power BI Desktop build contract."""
    semantic = semantic_model_contract(project_id, dataset_id)
    return {
        "stage": "6B",
        "project_id": project_id,
        "dataset_id": dataset_id,
        "desktop_file": POWERBI_DESKTOP_FILE_NAME,
        "storage_mode": "Import",
        "connector": semantic["connector"],
        "tables": semantic["tables"],
        "relationships": semantic["relationships"],
        "measures": [
            {
                "name": name,
                "display_folder": MEASURE_METADATA[name][0],
                "format_string": MEASURE_METADATA[name][1],
            }
            for name in MEASURE_NAMES
        ],
        "date_table": {
            "table": "dim_date",
            "date_column": "date",
            "sort_columns": {
                "month_name": "month_number",
                "day_name": "day_of_week_number",
            },
        },
        "field_hygiene": {
            "hide_join_keys": semantic["hide_from_report"],
            "prefer_explicit_measures": True,
            "implicit_monetary_measures_allowed": False,
        },
        "report_pages": list(REPORT_PAGE_NAMES),
        "acceptance": {
            "loaded_tables": len(PBI_TABLE_ALIASES),
            "active_relationships": len(RELATIONSHIPS),
            "explicit_measures": len(MEASURE_NAMES),
            "date_table_marked": True,
            "refresh_required": True,
            "minimum_report_pages": 1,
        },
    }


def inspect_stage6b(
    stage6a_root: Path = Path("artifacts/stage6a"),
    powerbi_root: Path = Path("powerbi"),
) -> DesktopReadiness:
    cloud_success = (stage6a_root / "_CLOUD_SUCCESS").is_file()
    semantic_present = (stage6a_root / "semantic_model_contract.json").is_file() or (
        powerbi_root / "semantic_model_contract.template.json"
    ).is_file()
    measures_present = (stage6a_root / "measures.dax").is_file() or (
        powerbi_root / "measures.dax"
    ).is_file()
    return DesktopReadiness(
        stage6a_cloud_success=cloud_success,
        semantic_contract_present=semantic_present,
        measure_library_present=measures_present,
        table_count=len(PBI_TABLE_ALIASES),
        relationship_count=len(RELATIONSHIPS),
        measure_count=len(MEASURE_NAMES),
        report_page_count=len(REPORT_PAGE_NAMES),
    )


def _write_relationship_csv(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "one_table",
                "one_column",
                "many_table",
                "many_column",
                "cardinality",
                "cross_filter",
                "active",
            ]
        )
        for dim, dim_col, fact, fact_col in RELATIONSHIPS:
            writer.writerow([dim, dim_col, fact, fact_col, "1:*", "Single", "YES"])


def _write_measure_csv(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["measure", "display_folder", "format_string", "required"])
        for name in MEASURE_NAMES:
            folder, format_string = MEASURE_METADATA[name]
            writer.writerow([name, folder, format_string, "YES"])


def _checklist_markdown(project_id: str, dataset_id: str) -> str:
    return f"""# PharmStock Stage 6B — Power BI Desktop Acceptance Checklist

## Connection
- [ ] Power BI Desktop 64-bit is used.
- [ ] Google BigQuery connector uses the new implementation / ADBC V2.
- [ ] Billing project: `{project_id}`.
- [ ] Dataset: `{dataset_id}`.
- [ ] Storage mode: Import.
- [ ] All 11 serving views are loaded.

## Semantic model
- [ ] `dim_date` is marked as the Date table using column `date`.
- [ ] `month_name` is sorted by `month_number`.
- [ ] `day_name` is sorted by `day_of_week_number`.
- [ ] All 17 relationships are active `1:*` and Single direction.
- [ ] Join keys are hidden from Report view where appropriate.
- [ ] All 18 explicit measures are added.
- [ ] `Fulfillment Rate` and `Procurement Fill Rate` are formatted as percentages.
- [ ] No price/revenue/cost/margin measure is created.

## Report
- [ ] `Operations Overview` page exists.
- [ ] KPI cards use explicit measures.
- [ ] Date/branch filters work across relevant visuals.
- [ ] Refresh completes successfully.
- [ ] File is saved as `{POWERBI_DESKTOP_FILE_NAME}` or an explicitly chosen PBIP project.

## Acceptance
Stage 6B is PASS only after the Power BI Desktop model itself satisfies every item above.
"""


def write_stage6b_build_kit(
    output_root: Path,
    *,
    project_id: str,
    dataset_id: str = DEFAULT_PBI_DATASET,
) -> dict[str, object]:
    """Write a deterministic build kit. This function never opens or mutates Power BI."""
    output_root.mkdir(parents=True, exist_ok=True)
    manifest = desktop_build_manifest(project_id, dataset_id)
    readiness = inspect_stage6b()

    (output_root / "desktop_build_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output_root / "dashboard_spec.json").write_text(
        json.dumps(dashboard_spec(), indent=2, sort_keys=True), encoding="utf-8"
    )
    (output_root / "bigquery_connection.m").write_text(
        connection_template(project_id), encoding="utf-8"
    )
    (output_root / "measures.dax").write_text(dax_measure_library(), encoding="utf-8")
    _write_relationship_csv(output_root / "relationships.csv")
    _write_measure_csv(output_root / "measures.csv")
    (output_root / "desktop_acceptance_checklist.md").write_text(
        _checklist_markdown(project_id, dataset_id), encoding="utf-8"
    )
    report = {
        "stage": "6B",
        "build_kit_ready": True,
        "desktop_mutation": False,
        "project_id": project_id,
        "dataset_id": dataset_id,
        "readiness": asdict(readiness),
        "table_count": len(PBI_TABLE_ALIASES),
        "relationship_count": len(RELATIONSHIPS),
        "measure_count": len(MEASURE_NAMES),
        "report_page_count": len(REPORT_PAGE_NAMES),
        "stage6b_pass_claimed": False,
    }
    (output_root / "build_kit_verification.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    return report
