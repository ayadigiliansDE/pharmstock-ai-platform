"""Stage 7H BigQuery deployment and dbt rebuild analytics contracts."""

from __future__ import annotations

import importlib.util
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pharmstock.rebuild.contracts import BIGQUERY_REBUILD_DATASET, SNAPSHOT_TABLES

DEFAULT_BQ_LOCATION: Final[str] = "EU"
DEFAULT_DBT_BASE_DATASET: Final[str] = "pharmstock"
STAGE7G_ROOT: Final[Path] = Path("artifacts/stage7g")
STAGE7H_ROOT: Final[Path] = Path("artifacts/stage7h")
STAGE7G_PLAN: Final[Path] = STAGE7G_ROOT / "bigquery_rebuild_plan.json"
STAGE7G_VERIFICATION: Final[Path] = STAGE7G_ROOT / "rebuild_verification.json"
STAGE7G_SUCCESS: Final[Path] = STAGE7G_ROOT / "_SUCCESS"

STAGE7H_STAGING_MODELS: Final[tuple[str, ...]] = (
    "stg7h_branch",
    "stg7h_product",
    "stg7h_supplier",
    "stg7h_sale_header",
    "stg7h_sale_line",
    "stg7h_demand_attempt",
    "stg7h_stock_movement",
    "stg7h_inventory_position",
    "stg7h_purchase_order",
    "stg7h_goods_receipt",
    "stg7h_goods_receipt_line",
)
STAGE7H_INTERMEDIATE_MODELS: Final[tuple[str, ...]] = (
    "int7h_sales_daily_branch_product",
    "int7h_demand_daily_branch_product",
    "int7h_inventory_daily_branch_product",
    "int7h_procurement_supplier_daily",
)
STAGE7H_GOLD_MODELS: Final[tuple[str, ...]] = (
    "mart7h_branch_daily_operations",
    "mart7h_product_daily_performance",
    "mart7h_supplier_performance",
)


@dataclass(frozen=True, slots=True)
class BigQueryLayout:
    """Physical BigQuery layout for one Stage 7G snapshot table."""

    partition_expression: str | None = None
    clustering_fields: tuple[str, ...] = ()


TABLE_LAYOUTS: Final[dict[str, BigQueryLayout]] = {
    "master.product": BigQueryLayout(clustering_fields=("product_id", "manufacturer")),
    "master.product_price_history": BigQueryLayout(
        "DATE(observed_at)", ("product_id", "price_type")
    ),
    "master.pharmacy_organization": BigQueryLayout(clustering_fields=("organization_id",)),
    "master.pharmacy_branch": BigQueryLayout(
        clustering_fields=("governorate_code", "organization_id")
    ),
    "commercial.product_unit_economics": BigQueryLayout(clustering_fields=("product_id",)),
    "commercial.branch_commercial_policy": BigQueryLayout(
        clustering_fields=("governorate_code", "branch_id")
    ),
    "pos.terminal": BigQueryLayout(clustering_fields=("branch_id",)),
    "customer.household": BigQueryLayout(clustering_fields=("preferred_branch_id",)),
    "customer.customer_profile": BigQueryLayout(
        clustering_fields=("preferred_branch_id", "customer_segment")
    ),
    "customer.loyalty_account": BigQueryLayout(clustering_fields=("customer_id",)),
    "customer.patient_profile": BigQueryLayout(clustering_fields=("household_id",)),
    "pos.prescription_context": BigQueryLayout(
        "DATE(recorded_at)", ("patient_id", "prescription_mode")
    ),
    "pos.demand_attempt": BigQueryLayout(
        "DATE(transaction_ts)", ("branch_id", "product_id", "outcome")
    ),
    "pos.sale_header": BigQueryLayout(
        "DATE(transaction_ts)", ("branch_id", "channel", "transaction_status")
    ),
    "pos.sale_line": BigQueryLayout(clustering_fields=("product_id", "sale_id")),
    "pos.payment": BigQueryLayout("DATE(paid_at)", ("payment_method", "sale_id")),
    "pos.return_header": BigQueryLayout("DATE(return_ts)", ("branch_id", "reason_code")),
    "pos.return_line": BigQueryLayout(clustering_fields=("product_id", "return_id")),
    "inventory.stock_batch": BigQueryLayout("expiry_date", ("branch_id", "product_id")),
    "inventory.inventory_position": BigQueryLayout(clustering_fields=("branch_id", "product_id")),
    "inventory.stock_movement": BigQueryLayout(
        "DATE(occurred_at)", ("branch_id", "product_id", "movement_type")
    ),
    "procurement.supplier": BigQueryLayout(clustering_fields=("supplier_type", "supplier_id")),
    "procurement.purchase_order": BigQueryLayout(
        "DATE(ordered_at)", ("branch_id", "supplier_id", "status")
    ),
    "procurement.purchase_order_line": BigQueryLayout(
        clustering_fields=("purchase_order_id", "product_id")
    ),
    "procurement.goods_receipt": BigQueryLayout(
        "DATE(received_at)", ("branch_id", "supplier_id", "status")
    ),
    "procurement.goods_receipt_line": BigQueryLayout(
        clustering_fields=("receipt_id", "product_id")
    ),
}


@dataclass(frozen=True, slots=True)
class Stage7HConfig:
    project_id: str | None
    dataset_id: str
    location: str
    dbt_base_dataset: str

    @property
    def project_configured(self) -> bool:
        return bool(self.project_id and self.project_id.strip())

    @property
    def dbt_gold_dataset(self) -> str:
        return f"{self.dbt_base_dataset}_rebuild_gold"

    @property
    def dbt_staging_dataset(self) -> str:
        return f"{self.dbt_base_dataset}_rebuild_stg"


def config_from_environment() -> Stage7HConfig:
    project = os.getenv("PHARMSTOCK_BQ_PROJECT", "").strip() or None
    dataset = os.getenv("PHARMSTOCK_BQ_REBUILD_DATASET", BIGQUERY_REBUILD_DATASET).strip()
    location = os.getenv("PHARMSTOCK_BQ_LOCATION", DEFAULT_BQ_LOCATION).strip()
    base = os.getenv("PHARMSTOCK_DBT_BASE_DATASET", DEFAULT_DBT_BASE_DATASET).strip()
    return Stage7HConfig(project, dataset, location, base)


def bigquery_client_installed() -> bool:
    try:
        return importlib.util.find_spec("google.cloud.bigquery") is not None
    except (ImportError, ModuleNotFoundError):
        return False


def dbt_installed() -> bool:
    try:
        return importlib.util.find_spec("dbt.cli.main") is not None
    except (ImportError, ModuleNotFoundError):
        return False


def credential_hint_present() -> bool:
    explicit = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    cloud_sdk_config = os.getenv("CLOUDSDK_CONFIG", "").strip()
    candidates = [
        Path.home() / ".config/gcloud/application_default_credentials.json",
    ]
    appdata = os.getenv("APPDATA", "").strip()
    if appdata:
        candidates.append(Path(appdata) / "gcloud/application_default_credentials.json")
    if cloud_sdk_config:
        candidates.append(Path(cloud_sdk_config) / "application_default_credentials.json")
    return bool(explicit or any(path.is_file() for path in candidates))


def _read_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def load_stage7g_plan(path: Path = STAGE7G_PLAN) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(f"Stage 7G BigQuery plan is missing: {path}")
    plan = _read_object(path)
    if plan.get("stage") != "7G":
        raise ValueError("Stage 7H requires a Stage 7G BigQuery rebuild plan")
    tables = plan.get("snapshot_tables")
    if not isinstance(tables, list) or len(tables) != len(SNAPSHOT_TABLES):
        raise ValueError("Stage 7G plan does not contain the complete 26-table snapshot")

    expected = {spec.source_table: spec for spec in SNAPSHOT_TABLES}
    seen: set[str] = set()
    for item in tables:
        if not isinstance(item, dict):
            raise ValueError("Stage 7G snapshot table plan entry is invalid")
        source_table = str(item.get("source_table", ""))
        spec = expected.get(source_table)
        if spec is None or source_table in seen:
            raise ValueError(f"unexpected or duplicate Stage 7G source table: {source_table}")
        seen.add(source_table)
        if tuple(item.get("primary_key", ())) != spec.primary_key:
            raise ValueError(f"Stage 7G primary key drift for {source_table}")
        if int(item.get("rows", -1)) < 0:
            raise ValueError(f"invalid Stage 7G row count for {source_table}")
        expected_target = f"{BIGQUERY_REBUILD_DATASET}.{spec.bigquery_table}"
        if item.get("target_table") != expected_target:
            raise ValueError(f"Stage 7G BigQuery target drift for {source_table}")
    if seen != set(expected):
        raise ValueError("Stage 7G BigQuery plan table set is incomplete")
    return plan


def parquet_files(path: Path) -> tuple[Path, ...]:
    return tuple(sorted(candidate for candidate in path.rglob("*.parquet") if candidate.is_file()))


def duplicate_primary_key_sql(table_id: str, primary_key: tuple[str, ...]) -> str:
    if not primary_key:
        raise ValueError("primary key is required")
    fields = ", ".join(f"`{field}`" for field in primary_key)
    return (
        "SELECT COUNT(*) FROM ("
        f"SELECT {fields}, COUNT(*) AS c FROM `{table_id}` "
        f"GROUP BY {fields} HAVING c > 1 LIMIT 1)"
    )


def atomic_replace_sql(
    *,
    target_table_id: str,
    staging_table_id: str,
    source_table: str,
    partitioning_enabled: bool = True,
) -> str:
    """Build the raw-table promotion DDL.

    ``partitioning_enabled=False`` is the BigQuery Sandbox fallback. Sandbox
    forces a 60-day partition lifetime, which would immediately drop historical
    partitions older than 60 days. The fallback keeps clustering but materializes
    the table unpartitioned so the complete historical snapshot survives for the
    table's sandbox lifetime.
    """
    layout = TABLE_LAYOUTS[source_table]
    clauses = [f"CREATE OR REPLACE TABLE `{target_table_id}`"]
    if partitioning_enabled and layout.partition_expression:
        clauses.append(f"PARTITION BY {layout.partition_expression}")
    if layout.clustering_fields:
        fields = ", ".join(f"`{field}`" for field in layout.clustering_fields)
        clauses.append(f"CLUSTER BY {fields}")
    clauses.append(f"AS SELECT * FROM `{staging_table_id}`")
    return "\n".join(clauses)


def dbt_project_ready(root: Path = Path("dbt/pharmstock_analytics")) -> tuple[bool, list[str]]:
    required = [
        root / "dbt_project.yml",
        root.parent / "profiles" / "profiles.yml",
        root / "models/rebuild_staging/_rebuild_sources.yml",
    ]
    required.extend(
        root / "models/rebuild_staging" / f"{name}.sql"
        for name in STAGE7H_STAGING_MODELS
    )
    required.extend(
        root / "models/rebuild_intermediate" / f"{name}.sql"
        for name in STAGE7H_INTERMEDIATE_MODELS
    )
    required.extend(root / "models/rebuild_marts" / f"{name}.sql" for name in STAGE7H_GOLD_MODELS)
    missing = [str(path) for path in required if not path.is_file()]
    return not missing, missing


def build_preflight(
    *,
    config: Stage7HConfig | None = None,
    stage7g_root: Path = STAGE7G_ROOT,
) -> dict[str, object]:
    config = config or config_from_environment()
    success = stage7g_root / "_SUCCESS"
    plan_path = stage7g_root / "bigquery_rebuild_plan.json"
    verification_path = stage7g_root / "rebuild_verification.json"
    if not success.is_file():
        raise RuntimeError("Stage 7H requires Stage 7G PASS")
    plan = load_stage7g_plan(plan_path)
    verification = _read_object(verification_path)
    if verification.get("status") != "PASS" or verification.get("bigquery_ready") is not True:
        raise RuntimeError("Stage 7G rebuild verification is not BigQuery-ready")

    table_checks: list[dict[str, object]] = []
    missing_files: list[str] = []
    expected_total = 0
    for item in plan["snapshot_tables"]:
        assert isinstance(item, dict)
        local = Path(str(item["local_parquet_path"]))
        files = parquet_files(local)
        rows = int(item["rows"])
        expected_total += rows
        if rows > 0 and not files:
            missing_files.append(str(local))
        table_checks.append(
            {
                "source_table": item["source_table"],
                "target_table": item["target_table"],
                "expected_rows": rows,
                "parquet_files": len(files),
                "local_path": str(local),
                "ready": bool(files) or rows == 0,
            }
        )

    verified_total = int(verification.get("snapshot_total_rows", -1))
    if expected_total != verified_total:
        raise RuntimeError(
            f"Stage 7G row-count plan mismatch expected_total={expected_total} "
            f"verification_total={verified_total}"
        )

    dbt_ready, dbt_missing = dbt_project_ready()
    bq_installed = bigquery_client_installed()
    dbt_package_installed = dbt_installed()
    credentials = credential_hint_present()
    cloud_ready = (
        not missing_files
        and config.project_configured
        and bq_installed
        and dbt_package_installed
        and dbt_ready
        and credentials
    )
    return {
        "stage": "7H",
        "mode": "LOCAL_SAFE_PREFLIGHT",
        "cloud_mutation": False,
        "stage7g_verified": True,
        "project_id": config.project_id,
        "dataset_id": config.dataset_id,
        "location": config.location,
        "dbt_base_dataset": config.dbt_base_dataset,
        "dbt_staging_dataset": config.dbt_staging_dataset,
        "dbt_gold_dataset": config.dbt_gold_dataset,
        "snapshot_table_count": len(table_checks),
        "expected_snapshot_rows": expected_total,
        "tables": table_checks,
        "missing_parquet_paths": missing_files,
        "bigquery_client_installed": bq_installed,
        "dbt_installed": dbt_package_installed,
        "dbt_project_ready": dbt_ready,
        "dbt_missing_files": dbt_missing,
        "credential_hint_present": credentials,
        "project_configured": config.project_configured,
        "local_ready": not missing_files and dbt_ready,
        "cloud_ready_hint": cloud_ready,
        "deployment_strategy": "STAGE_ALL_VALIDATE_ALL_THEN_PER_TABLE_ATOMIC_REPLACE",
        "historical_replay_through_kafka": False,
        "cdc_resume_offsets_preserved": True,
    }


def stage7h_contract() -> dict[str, object]:
    return {
        "stage": "7H",
        "flow": "STAGE7G_PARQUET -> BIGQUERY_RAW_REBUILD -> DBT_REBUILD_STG -> DBT_REBUILD_GOLD",
        "raw_dataset": BIGQUERY_REBUILD_DATASET,
        "raw_table_count": len(SNAPSHOT_TABLES),
        "layouts": {
            table: {
                "partition_expression": layout.partition_expression,
                "clustering_fields": list(layout.clustering_fields),
            }
            for table, layout in TABLE_LAYOUTS.items()
        },
        "dbt": {
            "staging_models": list(STAGE7H_STAGING_MODELS),
            "intermediate_models": list(STAGE7H_INTERMEDIATE_MODELS),
            "gold_models": list(STAGE7H_GOLD_MODELS),
        },
        "safety": {
            "checkpoint_cloud_mutation": False,
            "cloud_execution_requires_execute": True,
            "cloud_execution_requires_replace": True,
            "stage_all_before_promotion": True,
            "per_table_atomic_replace": True,
            "validate_row_counts": True,
            "validate_primary_keys": True,
        },
    }


__all__ = [
    "BIGQUERY_REBUILD_DATASET",
    "DEFAULT_BQ_LOCATION",
    "DEFAULT_DBT_BASE_DATASET",
    "STAGE7G_ROOT",
    "STAGE7H_GOLD_MODELS",
    "STAGE7H_INTERMEDIATE_MODELS",
    "STAGE7H_ROOT",
    "STAGE7H_STAGING_MODELS",
    "TABLE_LAYOUTS",
    "BigQueryLayout",
    "Stage7HConfig",
    "atomic_replace_sql",
    "bigquery_client_installed",
    "build_preflight",
    "config_from_environment",
    "credential_hint_present",
    "dbt_installed",
    "dbt_project_ready",
    "duplicate_primary_key_sql",
    "load_stage7g_plan",
    "parquet_files",
    "stage7h_contract",
]
