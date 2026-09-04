"""Stage 6A Power BI serving and semantic-model contract helpers."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_PBI_DATASET = "pharmstock_pbi"
DEFAULT_PROJECT_ID = "YOUR_PROJECT_ID"

PBI_MODEL_FILES = (
    "pbi_dim_date",
    "pbi_dim_product",
    "pbi_dim_branch",
    "pbi_dim_supplier",
    "pbi_fact_sales_demand",
    "pbi_fact_inventory_movement",
    "pbi_fact_reorder_events",
    "pbi_fact_procurement_order_lifecycle",
    "pbi_mart_branch_daily_operations",
    "pbi_mart_product_daily_demand",
    "pbi_mart_supplier_procurement_performance",
)

PBI_TABLE_ALIASES = {
    "pbi_dim_date": "dim_date",
    "pbi_dim_product": "dim_product",
    "pbi_dim_branch": "dim_branch",
    "pbi_dim_supplier": "dim_supplier",
    "pbi_fact_sales_demand": "fact_sales_demand",
    "pbi_fact_inventory_movement": "fact_inventory_movement",
    "pbi_fact_reorder_events": "fact_reorder_events",
    "pbi_fact_procurement_order_lifecycle": "fact_procurement_order_lifecycle",
    "pbi_mart_branch_daily_operations": "mart_branch_daily_operations",
    "pbi_mart_product_daily_demand": "mart_product_daily_demand",
    "pbi_mart_supplier_procurement_performance": "mart_supplier_procurement_performance",
}

FORBIDDEN_MONETARY_TERMS = (
    "price",
    "revenue",
    "cost",
    "margin",
    "sales_amount",
    "purchase_amount",
)

MEASURE_NAMES = (
    "Requested Units",
    "Fulfilled Units",
    "Lost Units",
    "Fulfillment Rate",
    "Demand Lines",
    "Baskets",
    "Inventory Units In",
    "Inventory Units Out",
    "Net Quantity Change",
    "Reorder Events",
    "Recommended Reorder Units",
    "Purchase Orders",
    "Ordered Units",
    "Received Units",
    "Procurement Fill Rate",
    "Restocked Units",
    "Active Branches",
    "Products With Demand",
)

RELATIONSHIPS = (
    ("dim_date", "date", "fact_sales_demand", "event_date"),
    ("dim_date", "date", "fact_inventory_movement", "event_date"),
    ("dim_date", "date", "fact_reorder_events", "event_date"),
    ("dim_date", "date", "fact_procurement_order_lifecycle", "order_date"),
    ("dim_date", "date", "mart_branch_daily_operations", "event_date"),
    ("dim_date", "date", "mart_product_daily_demand", "event_date"),
    ("dim_branch", "branch_id", "fact_sales_demand", "branch_id"),
    ("dim_branch", "branch_id", "fact_inventory_movement", "branch_id"),
    ("dim_branch", "branch_id", "fact_reorder_events", "branch_id"),
    ("dim_branch", "branch_id", "fact_procurement_order_lifecycle", "branch_id"),
    ("dim_branch", "branch_id", "mart_branch_daily_operations", "branch_id"),
    ("dim_product", "product_id", "fact_sales_demand", "product_id"),
    ("dim_product", "product_id", "fact_inventory_movement", "product_id"),
    ("dim_product", "product_id", "fact_reorder_events", "product_id"),
    ("dim_product", "product_id", "mart_product_daily_demand", "product_id"),
    ("dim_supplier", "supplier_id", "fact_procurement_order_lifecycle", "supplier_id"),
    ("dim_supplier", "supplier_id", "mart_supplier_procurement_performance", "supplier_id"),
)


@dataclass(frozen=True)
class PowerBIReadiness:
    project_files_ready: bool
    stage5d_dimensions_report_present: bool
    project_configured: bool
    pbi_model_count: int
    relationship_count: int
    measure_count: int
    cloud_mutation: bool = False


def _relationship_contract() -> list[dict[str, str]]:
    return [
        {
            "from_table": dim,
            "from_column": dim_col,
            "to_table": fact,
            "to_column": fact_col,
            "cardinality": "one_to_many",
            "cross_filter_direction": "single",
        }
        for dim, dim_col, fact, fact_col in RELATIONSHIPS
    ]


def semantic_model_contract(project_id: str, dataset_id: str) -> dict[str, object]:
    """Return the source-controlled semantic contract for Power BI authoring."""
    tables = [
        {
            "name": alias,
            "bigquery_table": f"{project_id}.{dataset_id}.{alias}",
            "storage_mode": "Import",
            "source_type": "BigQuery View",
        }
        for alias in PBI_TABLE_ALIASES.values()
    ]
    return {
        "stage": "6A",
        "project_id": project_id,
        "dataset_id": dataset_id,
        "connector": {
            "name": "Google BigQuery",
            "implementation": "2.0",
            "driver_family": "ADBC",
            "billing_project": project_id,
            "recommended_initial_storage_mode": "Import",
        },
        "tables": tables,
        "relationships": _relationship_contract(),
        "measures": list(MEASURE_NAMES),
        "hide_from_report": [
            "product_id",
            "branch_id",
            "supplier_id",
            "purchase_order_id",
            "event_id",
        ],
        "truth_boundary": {
            "product_catalog": "official_openFDA_NDC_US_reference",
            "pharmacy_network": "synthetic_Egypt",
            "supplier_network": "synthetic",
            "authoritative_monetary_data": False,
        },
    }


def connection_template(project_id: str) -> str:
    """Return a minimal Power Query source expression using the BigQuery ADBC connector."""
    return (
        "let\n"
        "    Source = GoogleBigQuery.Database([\n"
        f'        BillingProject = "{project_id}",\n'
        '        Implementation = "2.0"\n'
        "    ])\n"
        "in\n"
        "    Source\n"
    )


def dax_measure_library() -> str:
    """Return explicit non-monetary DAX measures for the first semantic model."""
    return """-- PharmStock Stage 6A explicit measures\n\n""" + "\n\n".join(
        (
            "Requested Units := SUM('fact_sales_demand'[requested_units])",
            "Fulfilled Units := SUM('fact_sales_demand'[fulfilled_units])",
            "Lost Units := SUM('fact_sales_demand'[lost_units])",
            "Fulfillment Rate := DIVIDE([Fulfilled Units], [Requested Units])",
            "Demand Lines := SUM('fact_sales_demand'[demand_line_events])",
            "Baskets := SUM('fact_sales_demand'[baskets])",
            "Inventory Units In := SUM('fact_inventory_movement'[units_in])",
            "Inventory Units Out := SUM('fact_inventory_movement'[units_out])",
            "Net Quantity Change := SUM('fact_inventory_movement'[net_quantity_delta])",
            "Reorder Events := COUNTROWS('fact_reorder_events')",
            "Recommended Reorder Units := "
            "SUM('fact_reorder_events'[recommended_reorder_quantity])",
            "Purchase Orders := "
            "DISTINCTCOUNT('fact_procurement_order_lifecycle'[purchase_order_id])",
            "Ordered Units := SUM('fact_procurement_order_lifecycle'[ordered_units])",
            "Received Units := SUM('fact_procurement_order_lifecycle'[received_units])",
            "Procurement Fill Rate := DIVIDE([Received Units], [Ordered Units])",
            "Restocked Units := SUM('fact_procurement_order_lifecycle'[restocked_units])",
            "Active Branches := DISTINCTCOUNT('fact_sales_demand'[branch_id])",
            "Products With Demand := DISTINCTCOUNT('fact_sales_demand'[product_id])",
        )
    ) + "\n"


def inspect_stage6a(
    project_root: Path = Path("dbt/pharmstock_analytics"),
    stage5d_root: Path = Path("artifacts/stage5d"),
) -> PowerBIReadiness:
    serving = project_root / "models" / "powerbi_serving"
    existing = {path.stem for path in serving.glob("*.sql")}
    project_ready = existing == set(PBI_MODEL_FILES)
    dimension_report = stage5d_root / "dimensions_execution_report.json"
    project_id = os.getenv("PHARMSTOCK_BQ_PROJECT", "").strip()
    return PowerBIReadiness(
        project_files_ready=project_ready,
        stage5d_dimensions_report_present=dimension_report.is_file(),
        project_configured=bool(project_id),
        pbi_model_count=len(existing),
        relationship_count=len(RELATIONSHIPS),
        measure_count=len(MEASURE_NAMES),
    )


def write_stage6a_local_artifacts(
    output_root: Path,
    *,
    project_id: str | None = None,
    dataset_id: str = DEFAULT_PBI_DATASET,
) -> dict[str, object]:
    """Write deterministic local semantic assets; never contacts Google Cloud."""
    resolved_project = project_id or os.getenv("PHARMSTOCK_BQ_PROJECT", DEFAULT_PROJECT_ID)
    if not resolved_project:
        resolved_project = DEFAULT_PROJECT_ID
    output_root.mkdir(parents=True, exist_ok=True)
    contract = semantic_model_contract(resolved_project, dataset_id)
    (output_root / "semantic_model_contract.json").write_text(
        json.dumps(contract, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output_root / "bigquery_connection.m").write_text(
        connection_template(resolved_project), encoding="utf-8"
    )
    (output_root / "measures.dax").write_text(dax_measure_library(), encoding="utf-8")
    readiness = inspect_stage6a()
    report = {
        "stage": "6A",
        "cloud_mutation": False,
        "powerbi_dataset": dataset_id,
        "readiness": asdict(readiness),
        "table_count": len(PBI_MODEL_FILES),
        "relationship_count": len(RELATIONSHIPS),
        "measure_count": len(MEASURE_NAMES),
        "monetary_measures_generated": False,
    }
    (output_root / "local_verification.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    return report
