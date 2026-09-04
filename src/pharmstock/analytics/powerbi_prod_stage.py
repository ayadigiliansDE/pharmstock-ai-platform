"""Stage 7N production Power BI semantic-serving contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

STAGE7N_VERSION: Final[str] = "0.38.0"
DEFAULT_PBI_PROD_DATASET: Final[str] = "pharmstock_pbi_prod"
DEFAULT_POSTGRES_BI_SCHEMA: Final[str] = "bi"

BIGQUERY_VIEWS: Final[tuple[str, ...]] = (
    "dim_date",
    "dim_branch",
    "dim_product",
    "dim_supplier",
    "fact_branch_daily_operations",
    "fact_product_daily_performance",
    "fact_supplier_performance",
    "snapshot_inventory_position",
    "snapshot_batch_expiry",
)

POSTGRES_VIEWS: Final[tuple[str, ...]] = (
    "v_ml_demand_forecast",
    "v_ml_branch_product_decision",
    "v_ml_expiry_risk",
    "v_decision_case",
    "v_decision_audit",
)

MEASURES: Final[tuple[tuple[str, str, str], ...]] = (
    ("Requested Units", "SUM('fact_branch_daily_operations'[requested_units])", "0"),
    ("Fulfilled Units", "SUM('fact_branch_daily_operations'[fulfilled_units])", "0"),
    ("Lost Units", "SUM('fact_branch_daily_operations'[lost_units])", "0"),
    ("Fill Rate", "DIVIDE([Fulfilled Units], [Requested Units])", "0.0%"),
    ("Stockout Attempts", "SUM('fact_branch_daily_operations'[stockout_attempts])", "0"),
    ("Sales Transactions", "SUM('fact_branch_daily_operations'[sales_transactions])", "0"),
    ("Units Sold", "SUM('fact_branch_daily_operations'[units_sold])", "0"),
    ("Net Sales EGP", "SUM('fact_branch_daily_operations'[net_sales_egp])", "#,##0.00"),
    ("Modeled COGS EGP", "SUM('fact_branch_daily_operations'[cogs_egp])", "#,##0.00"),
    (
        "Modeled Gross Profit EGP",
        "SUM('fact_branch_daily_operations'[gross_profit_egp])",
        "#,##0.00",
    ),
    (
        "Modeled Gross Margin",
        "DIVIDE([Modeled Gross Profit EGP], [Net Sales EGP])",
        "0.0%",
    ),
    ("Current On Hand Units", "SUM('snapshot_inventory_position'[on_hand_units])", "0"),
    ("Current Available Units", "SUM('snapshot_inventory_position'[available_units])", "0"),
    (
        "Below Reorder Positions",
        "CALCULATE(COUNTROWS('snapshot_inventory_position'), "
        "'snapshot_inventory_position'[below_reorder] = TRUE())",
        "0",
    ),
    (
        "Zero Stock Positions",
        "CALCULATE(COUNTROWS('snapshot_inventory_position'), "
        "'snapshot_inventory_position'[available_units] = 0)",
        "0",
    ),
    (
        "Near Expiry Batches",
        "CALCULATE(COUNTROWS('snapshot_batch_expiry'), "
        "'snapshot_batch_expiry'[expiry_bucket] IN {\"0-30 days\", \"31-90 days\"})",
        "0",
    ),
    (
        "Expired Batches",
        "CALCULATE(COUNTROWS('snapshot_batch_expiry'), "
        "'snapshot_batch_expiry'[days_to_expiry] < 0)",
        "0",
    ),
    ("Supplier Purchase Orders", "SUM('fact_supplier_performance'[purchase_orders])", "0"),
    (
        "Supplier Delayed Receipt Rate",
        "DIVIDE(SUM('fact_supplier_performance'[delayed_receipts]), "
        "SUM('fact_supplier_performance'[goods_receipts]))",
        "0.0%",
    ),
    (
        "Average Supplier Lead Time Days",
        "AVERAGE('fact_supplier_performance'[average_actual_lead_time_days])",
        "0.0",
    ),
    (
        "Open Decision Cases",
        "CALCULATE(COUNTROWS('v_decision_case'), "
        "'v_decision_case'[status] IN {\"OPEN\", \"ACKNOWLEDGED\"})",
        "0",
    ),
    (
        "High Priority Cases",
        "CALCULATE(COUNTROWS('v_decision_case'), "
        "'v_decision_case'[severity] IN {\"HIGH\", \"CRITICAL\"}, "
        "'v_decision_case'[status] IN {\"OPEN\", \"ACKNOWLEDGED\"})",
        "0",
    ),
    (
        "Approved Replenishment Drafts",
        "CALCULATE(COUNTROWS('v_decision_case'), "
        "'v_decision_case'[status] = \"APPROVED_DRAFT\")",
        "0",
    ),
    (
        "Decision Acceptance Rate",
        "DIVIDE(CALCULATE(COUNTROWS('v_decision_case'), "
        "'v_decision_case'[status] = \"APPROVED_DRAFT\"), "
        "CALCULATE(COUNTROWS('v_decision_case'), "
        "'v_decision_case'[status] IN {\"APPROVED_DRAFT\", \"REJECTED\"}))",
        "0.0%",
    ),
)


@dataclass(frozen=True, slots=True)
class Stage7NReadiness:
    stage7h_cloud_report_present: bool
    stage7j_dq_report_present: bool
    stage7m_report_present: bool
    postgres_sql_present: bool
    bigquery_view_count: int
    postgres_view_count: int
    measure_count: int


def bigquery_view_sql(
    *,
    project_id: str,
    gold_dataset: str = "pharmstock_rebuild_gold",
    current_dataset: str = "pharmstock_ops_current",
) -> dict[str, str]:
    """Return the production BigQuery semantic views; all are metadata-only views."""
    gold = f"`{project_id}.{gold_dataset}"
    current = f"`{project_id}.{current_dataset}"
    return {
        "dim_date": f"""
WITH bounds AS (
  SELECT MIN(business_date) AS min_date, MAX(business_date) AS max_date
  FROM {gold}.mart7h_branch_daily_operations`
), calendar AS (
  SELECT d AS date
  FROM bounds, UNNEST(GENERATE_DATE_ARRAY(min_date, max_date)) AS d
  WHERE min_date IS NOT NULL AND max_date IS NOT NULL
)
SELECT
  date,
  EXTRACT(YEAR FROM date) AS year,
  EXTRACT(QUARTER FROM date) AS quarter_number,
  CONCAT('Q', CAST(EXTRACT(QUARTER FROM date) AS STRING)) AS quarter,
  EXTRACT(MONTH FROM date) AS month_number,
  FORMAT_DATE('%B', date) AS month_name,
  FORMAT_DATE('%Y-%m', date) AS year_month,
  EXTRACT(WEEK FROM date) AS week_number,
  EXTRACT(DAY FROM date) AS day_of_month,
  FORMAT_DATE('%A', date) AS day_name,
  EXTRACT(DAYOFWEEK FROM date) AS day_of_week_number,
  EXTRACT(DAYOFWEEK FROM date) IN (1, 7) AS is_weekend
FROM calendar
""".strip(),
        "dim_branch": f"""
SELECT DISTINCT
  branch_id,
  branch_code,
  branch_name,
  governorate_code,
  governorate,
  locality_type
FROM {gold}.mart7h_branch_daily_operations`
WHERE branch_id IS NOT NULL
""".strip(),
        "dim_product": f"""
SELECT
  product_id,
  trade_name_en,
  scientific_name,
  manufacturer,
  retail_price_egp,
  product_price_provenance
FROM {gold}.mart7h_product_daily_performance`
WHERE product_id IS NOT NULL
QUALIFY ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY business_date DESC) = 1
""".strip(),
        "dim_supplier": f"""
SELECT
  supplier_id,
  supplier_code,
  supplier_name,
  supplier_type,
  service_scope,
  reliability_score,
  nominal_lead_time_days
FROM {gold}.mart7h_supplier_performance`
WHERE supplier_id IS NOT NULL
""".strip(),
        "fact_branch_daily_operations": (
            f"SELECT * FROM {gold}.mart7h_branch_daily_operations`"
        ),
        "fact_product_daily_performance": (
            f"SELECT * FROM {gold}.mart7h_product_daily_performance`"
        ),
        "fact_supplier_performance": f"SELECT * FROM {gold}.mart7h_supplier_performance`",
        "snapshot_inventory_position": f"""
SELECT
  ip.branch_id,
  b.branch_code,
  b.display_name AS branch_name,
  b.governorate,
  b.representative_city,
  ip.product_id,
  p.trade_name_en,
  p.scientific_name,
  p.manufacturer,
  ip.on_hand_units,
  ip.reserved_units,
  ip.available_units,
  ip.reorder_point_units,
  ip.target_stock_units,
  ip.available_units <= ip.reorder_point_units AS below_reorder,
  SAFE_DIVIDE(ip.available_units, NULLIF(ip.target_stock_units, 0)) AS target_coverage_ratio,
  ip.last_movement_at,
  ip.updated_at
FROM {current}.inventory__inventory_position` ip
LEFT JOIN {current}.master__pharmacy_branch` b USING (branch_id)
LEFT JOIN {current}.master__product` p USING (product_id)
""".strip(),
        "snapshot_batch_expiry": f"""
SELECT
  sb.batch_id,
  sb.branch_id,
  b.branch_code,
  b.display_name AS branch_name,
  b.governorate,
  sb.product_id,
  p.trade_name_en,
  p.scientific_name,
  p.manufacturer,
  sb.batch_code,
  sb.expiry_date,
  DATE_DIFF(sb.expiry_date, CURRENT_DATE('Africa/Cairo'), DAY) AS days_to_expiry,
  CASE
    WHEN sb.expiry_date < CURRENT_DATE('Africa/Cairo') THEN 'Expired'
    WHEN DATE_DIFF(sb.expiry_date, CURRENT_DATE('Africa/Cairo'), DAY) <= 30 THEN '0-30 days'
    WHEN DATE_DIFF(sb.expiry_date, CURRENT_DATE('Africa/Cairo'), DAY) <= 90 THEN '31-90 days'
    WHEN DATE_DIFF(sb.expiry_date, CURRENT_DATE('Africa/Cairo'), DAY) <= 180 THEN '91-180 days'
    ELSE '180+ days'
  END AS expiry_bucket,
  sb.quantity_received,
  sb.quantity_on_hand,
  sb.purchase_cost_egp,
  sb.retail_unit_price_egp,
  sb.status,
  sb.received_at,
  sb.updated_at
FROM {current}.inventory__stock_batch` sb
LEFT JOIN {current}.master__pharmacy_branch` b USING (branch_id)
LEFT JOIN {current}.master__product` p USING (product_id)
WHERE sb.quantity_on_hand > 0
""".strip(),
    }


def semantic_contract(
    project_id: str,
    *,
    bigquery_dataset: str = DEFAULT_PBI_PROD_DATASET,
    postgres_host: str = "localhost",
    postgres_port: int = 5433,
    postgres_database: str = "pharmstock_ops",
) -> dict[str, object]:
    bigquery_tables = [
        {
            "name": name,
            "source": f"{project_id}.{bigquery_dataset}.{name}",
            "source_type": "BigQuery View",
            "storage_mode": "Import",
        }
        for name in BIGQUERY_VIEWS
    ]
    postgres_tables = [
        {
            "name": name,
            "source": f"{DEFAULT_POSTGRES_BI_SCHEMA}.{name}",
            "source_type": "PostgreSQL Read-Only View",
            "storage_mode": "Import",
        }
        for name in POSTGRES_VIEWS
    ]
    return {
        "stage": "7N",
        "version": STAGE7N_VERSION,
        "model_name": "PharmStock Production Semantic Model",
        "sources": {
            "bigquery": {
                "project_id": project_id,
                "dataset_id": bigquery_dataset,
                "connector": "Google BigQuery / ADBC v2",
                "recommended_mode": "Import",
            },
            "postgresql": {
                "host": postgres_host,
                "port": postgres_port,
                "database": postgres_database,
                "schema": DEFAULT_POSTGRES_BI_SCHEMA,
                "connector": "PostgreSQL",
                "recommended_mode": "Import",
                "production_refresh_note": "Power BI Service requires an on-premises data gateway",
            },
        },
        "tables": bigquery_tables + postgres_tables,
        "relationships": [
            ["dim_date", "date", "fact_branch_daily_operations", "business_date"],
            ["dim_date", "date", "fact_product_daily_performance", "business_date"],
            ["dim_branch", "branch_id", "fact_branch_daily_operations", "branch_id"],
            ["dim_product", "product_id", "fact_product_daily_performance", "product_id"],
            ["dim_supplier", "supplier_id", "fact_supplier_performance", "supplier_id"],
            ["dim_branch", "branch_id", "snapshot_inventory_position", "branch_id"],
            ["dim_product", "product_id", "snapshot_inventory_position", "product_id"],
            ["dim_branch", "branch_id", "snapshot_batch_expiry", "branch_id"],
            ["dim_product", "product_id", "snapshot_batch_expiry", "product_id"],
            ["dim_branch", "branch_id", "v_ml_branch_product_decision", "branch_id"],
            ["dim_product", "product_id", "v_ml_branch_product_decision", "product_id"],
            ["dim_product", "product_id", "v_ml_demand_forecast", "product_id"],
            ["dim_branch", "branch_id", "v_ml_expiry_risk", "branch_id"],
            ["dim_product", "product_id", "v_ml_expiry_risk", "product_id"],
            ["dim_branch", "branch_id", "v_decision_case", "branch_id"],
            ["dim_product", "product_id", "v_decision_case", "product_id"],
        ],
        "measures": [
            {"name": name, "expression": expression, "format": fmt}
            for name, expression, fmt in MEASURES
        ],
        "truth_boundary": {
            "pharmacy_network": "SYNTHETIC_CALIBRATED_EGYPT",
            "retail_price": "PUBLIC_MARKET_EGYPT",
            "purchase_cost_and_margin": "SYNTHETIC_CALIBRATED_MODELED",
            "ml_training_provenance": (
                "SYNTHETIC_CALIBRATED_OFFLINE_BACKFILL_"
                "UNTIL_REAL_HISTORY_SUFFICIENT"
            ),
            "decision_workflow": "REAL_RUNTIME_STATE_OF_THE_SIMULATED_PHARMACY_PLATFORM",
        },
        "type_rules": {
            "uuid_keys": "Text",
            "date_keys": "Date",
            "timestamps": "Date/Time/Timezone as supported by connector",
            "rates": "Decimal Number",
            "currency_egp": "Fixed Decimal Number",
        },
        "governance": {
            "powerbi_role": "pharmstock_bi",
            "database_access": "READ_ONLY",
            "procurement_write": False,
            "ml_write": False,
            "decision_write": False,
        },
    }


def dax_library() -> str:
    return "\n\n".join(
        f"{name} := {expression}\n-- Format: {fmt}" for name, expression, fmt in MEASURES
    ) + "\n"


def report_spec() -> dict[str, object]:
    return {
        "stage": "7N",
        "version": STAGE7N_VERSION,
        "pages": [
            {
                "name": "Executive Operations",
                "purpose": "Network demand, fulfillment, stockout and modeled financial health",
                "kpis": [
                    "Net Sales EGP",
                    "Modeled Gross Profit EGP",
                    "Fill Rate",
                    "Lost Units",
                    "Stockout Attempts",
                ],
            },
            {
                "name": "Branch & Demand",
                "purpose": "Governorate and branch performance with daily demand trends",
                "kpis": ["Requested Units", "Fulfilled Units", "Lost Units", "Fill Rate"],
            },
            {
                "name": "Inventory & Expiry",
                "purpose": "Current stock position, reorder pressure and FEFO expiry exposure",
                "kpis": [
                    "Current On Hand Units",
                    "Current Available Units",
                    "Below Reorder Positions",
                    "Near Expiry Batches",
                    "Expired Batches",
                ],
            },
            {
                "name": "Supplier & Procurement",
                "purpose": "Supplier reliability, delays, lead time and modeled procurement cost",
                "kpis": [
                    "Supplier Purchase Orders",
                    "Supplier Delayed Receipt Rate",
                    "Average Supplier Lead Time Days",
                ],
            },
            {
                "name": "AI & Decision Operations",
                "purpose": "ML recommendations, governed cases, approvals and audit outcomes",
                "kpis": [
                    "Open Decision Cases",
                    "High Priority Cases",
                    "Approved Replenishment Drafts",
                    "Decision Acceptance Rate",
                ],
            },
        ],
    }


def write_stage7n_artifacts(output_root: Path, *, project_id: str) -> dict[str, object]:
    output_root.mkdir(parents=True, exist_ok=True)
    contract = semantic_contract(project_id)
    (output_root / "semantic_model_contract.json").write_text(
        json.dumps(contract, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output_root / "measures.dax").write_text(dax_library(), encoding="utf-8")
    (output_root / "report_spec.json").write_text(
        json.dumps(report_spec(), indent=2, sort_keys=True), encoding="utf-8"
    )
    bigquery_m = (
        "let\n"
        "    Source = GoogleBigQuery.Database([\n"
        f'        BillingProject = "{project_id}",\n'
        '        Implementation = "2.0"\n'
        "    ])\n"
        "in\n"
        "    Source\n"
    )
    postgres_m = (
        "let\n"
        '    Source = PostgreSQL.Database("localhost:5433", "pharmstock_ops")\n'
        "in\n"
        "    Source\n"
    )
    (output_root / "bigquery_connection.m").write_text(bigquery_m, encoding="utf-8")
    (output_root / "postgres_connection.m").write_text(postgres_m, encoding="utf-8")
    checklist = "\n".join(
        (
            "# Stage 7N Power BI Desktop checklist",
            "",
            "- Connect BigQuery to `pharmstock_pbi_prod` using ADBC v2.",
            "- Connect PostgreSQL to schema `bi` using read-only role `pharmstock_bi`.",
            "- Import all 14 semantic views.",
            "- Create the 16 one-to-many, single-direction relationships from the contract.",
            "- Mark `dim_date[date]` as the Date table.",
            "- Add the explicit measures from `measures.dax`.",
            "- Hide UUID technical columns after relationships are created.",
            "- Build the five pages from `report_spec.json`.",
            "- Preserve truth-boundary labels for public-market retail price and modeled costs.",
            "- Do not create writeback, PO, supplier-selection or ML-execution actions.",
            "",
        )
    )
    (output_root / "desktop_build_checklist.md").write_text(checklist, encoding="utf-8")
    return {
        "stage": "7N",
        "version": STAGE7N_VERSION,
        "cloud_mutation": False,
        "bigquery_views": len(BIGQUERY_VIEWS),
        "postgres_views": len(POSTGRES_VIEWS),
        "measure_count": len(MEASURES),
        "relationship_count": len(contract["relationships"]),
        "report_page_count": len(report_spec()["pages"]),
    }
