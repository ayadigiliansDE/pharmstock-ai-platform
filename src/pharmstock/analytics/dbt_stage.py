"""Dependency-light Stage 5C dbt analytics project contract and local readiness checks."""

from __future__ import annotations

import importlib.util
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

DBT_PROJECT_RELATIVE: Final[Path] = Path("dbt/pharmstock_analytics")
DBT_PROFILES_RELATIVE: Final[Path] = Path("dbt/profiles")
DEFAULT_DBT_BASE_DATASET: Final[str] = "pharmstock"
DEFAULT_SOURCE_DATASET: Final[str] = "pharmstock_silver"
DEFAULT_LOCATION: Final[str] = "EU"

STAGING_MODELS: Final[tuple[str, ...]] = (
    "stg_event_index",
    "stg_sales_units_fulfilled",
    "stg_inventory_quantity_changed",
    "stg_inventory_reorder_required",
    "stg_purchase_order_created",
    "stg_goods_receipt_received",
    "stg_restock_applied",
)

INTERMEDIATE_MODELS: Final[tuple[str, ...]] = (
    "int_sales_daily_branch_product",
    "int_inventory_daily_branch_product",
    "int_procurement_order_lifecycle",
)

GOLD_MODELS: Final[tuple[str, ...]] = (
    "fct_daily_sales_demand",
    "fct_daily_inventory_movement",
    "fct_reorder_events",
    "fct_procurement_order_lifecycle",
    "mart_branch_daily_operations",
    "mart_product_daily_demand",
    "mart_supplier_procurement_performance",
)

FORBIDDEN_MONETARY_TOKENS: Final[tuple[str, ...]] = (
    "revenue",
    "unit_price",
    "sale_price",
    "purchase_price",
    "unit_cost",
    "total_cost",
    "gross_margin",
)


@dataclass(frozen=True, slots=True)
class DbtStage5CConfig:
    project_id: str | None
    source_dataset: str
    base_dataset: str
    location: str

    @property
    def gold_dataset(self) -> str:
        return f"{self.base_dataset}_gold"

    @property
    def staging_dataset(self) -> str:
        return f"{self.base_dataset}_stg"

    @property
    def project_configured(self) -> bool:
        return bool(self.project_id and self.project_id.strip())


@dataclass(frozen=True, slots=True)
class DbtStage5CReadiness:
    project_files_ready: bool
    dbt_installed: bool
    project_configured: bool
    stage5b_cloud_report_present: bool
    staging_model_count: int
    intermediate_model_count: int
    gold_model_count: int
    data_test_count: int
    issues: tuple[str, ...]

    @property
    def local_ready(self) -> bool:
        return self.project_files_ready and self.dbt_installed

    @property
    def cloud_ready_hint(self) -> bool:
        return self.local_ready and self.project_configured and self.stage5b_cloud_report_present

    def to_dict(self) -> dict[str, object]:
        return {
            "project_files_ready": self.project_files_ready,
            "dbt_installed": self.dbt_installed,
            "project_configured": self.project_configured,
            "stage5b_cloud_report_present": self.stage5b_cloud_report_present,
            "local_ready": self.local_ready,
            "cloud_ready_hint": self.cloud_ready_hint,
            "staging_model_count": self.staging_model_count,
            "intermediate_model_count": self.intermediate_model_count,
            "gold_model_count": self.gold_model_count,
            "data_test_count": self.data_test_count,
            "issues": list(self.issues),
        }


def config_from_environment() -> DbtStage5CConfig:
    project = os.getenv("PHARMSTOCK_BQ_PROJECT", "").strip() or None
    source = os.getenv("PHARMSTOCK_BQ_SOURCE_DATASET", DEFAULT_SOURCE_DATASET).strip()
    base = os.getenv("PHARMSTOCK_DBT_BASE_DATASET", DEFAULT_DBT_BASE_DATASET).strip()
    location = os.getenv("PHARMSTOCK_BQ_LOCATION", DEFAULT_LOCATION).strip()
    return DbtStage5CConfig(project, source, base, location)


def dbt_installed() -> bool:
    try:
        return importlib.util.find_spec("dbt.cli.main") is not None
    except (ImportError, ModuleNotFoundError):
        return False


def _model_names(root: Path, folder: str) -> tuple[str, ...]:
    path = root / "models" / folder
    return tuple(sorted(file.stem for file in path.glob("*.sql"))) if path.exists() else ()


def inspect_stage5c_project(
    project_root: Path,
    stage5b_root: Path = Path("artifacts/stage5b"),
    *,
    installed: bool | None = None,
    config: DbtStage5CConfig | None = None,
) -> DbtStage5CReadiness:
    config = config or config_from_environment()
    issues: list[str] = []
    required_files = (
        project_root / "dbt_project.yml",
        project_root.parent / "profiles" / "profiles.yml",
        project_root / "models" / "staging" / "_sources.yml",
        project_root / "models" / "marts" / "_marts.yml",
    )
    missing = [str(path) for path in required_files if not path.is_file()]
    if missing:
        issues.extend(f"missing dbt project file: {path}" for path in missing)

    staging = _model_names(project_root, "staging")
    intermediate = _model_names(project_root, "intermediate")
    gold = _model_names(project_root, "marts")
    if set(staging) != set(STAGING_MODELS):
        issues.append("Stage 5C staging model set does not match contract")
    if set(intermediate) != set(INTERMEDIATE_MODELS):
        issues.append("Stage 5C intermediate model set does not match contract")
    if set(gold) != set(GOLD_MODELS):
        issues.append("Stage 5C Gold model set does not match contract")

    test_root = project_root / "tests"
    data_tests = tuple(sorted(test_root.glob("*.sql"))) if test_root.exists() else ()
    if len(data_tests) < 9:
        issues.append("Stage 5C requires at least 9 singular data-quality tests")

    installed_value = dbt_installed() if installed is None else installed
    if not installed_value:
        issues.append('dbt is not installed; use pip install -e ".[analytics]"')
    if not config.project_configured:
        issues.append("PHARMSTOCK_BQ_PROJECT is not configured")

    cloud_report = stage5b_root / "cloud_execution_report.json"
    cloud_report_present = cloud_report.is_file()
    if not cloud_report_present:
        issues.append("Stage 5B cloud_execution_report.json is not present")

    files_ready = not missing and set(staging) == set(STAGING_MODELS)
    files_ready = files_ready and set(intermediate) == set(INTERMEDIATE_MODELS)
    files_ready = files_ready and set(gold) == set(GOLD_MODELS) and len(data_tests) >= 9
    return DbtStage5CReadiness(
        project_files_ready=files_ready,
        dbt_installed=installed_value,
        project_configured=config.project_configured,
        stage5b_cloud_report_present=cloud_report_present,
        staging_model_count=len(staging),
        intermediate_model_count=len(intermediate),
        gold_model_count=len(gold),
        data_test_count=len(data_tests),
        issues=tuple(issues),
    )


def build_analytics_catalog(config: DbtStage5CConfig) -> dict[str, object]:
    return {
        "stage": "5C",
        "source_dataset": config.source_dataset,
        "staging_dataset": config.staging_dataset,
        "gold_dataset": config.gold_dataset,
        "staging_models": list(STAGING_MODELS),
        "intermediate_models": list(INTERMEDIATE_MODELS),
        "gold_models": list(GOLD_MODELS),
        "power_bi_ready": list(GOLD_MODELS),
        "monetary_measures_generated": False,
        "master_dimensions_complete": False,
        "master_dimension_note": (
            "Full product/branch/supplier master dimensions require a later warehouse extension; "
            "Stage 5C does not fabricate master attributes from event IDs."
        ),
    }


def write_local_stage5c_plan(
    output_root: Path,
    project_root: Path,
    stage5b_root: Path = Path("artifacts/stage5b"),
) -> dict[str, object]:
    config = config_from_environment()
    readiness = inspect_stage5c_project(project_root, stage5b_root, config=config)
    output_root.mkdir(parents=True, exist_ok=True)
    catalog = build_analytics_catalog(config)
    plan = {
        "stage": "5C",
        "mode": "local_safe_preflight",
        "cloud_mutation": False,
        "readiness": readiness.to_dict(),
        "catalog": catalog,
    }
    (output_root / "local_readiness.json").write_text(
        json.dumps(readiness.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
    )
    (output_root / "analytics_catalog.json").write_text(
        json.dumps(catalog, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output_root / "deployment_plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8"
    )
    return plan


__all__ = [
    "DBT_PROFILES_RELATIVE",
    "DBT_PROJECT_RELATIVE",
    "DEFAULT_DBT_BASE_DATASET",
    "DEFAULT_LOCATION",
    "DEFAULT_SOURCE_DATASET",
    "FORBIDDEN_MONETARY_TOKENS",
    "GOLD_MODELS",
    "INTERMEDIATE_MODELS",
    "STAGING_MODELS",
    "DbtStage5CConfig",
    "DbtStage5CReadiness",
    "build_analytics_catalog",
    "config_from_environment",
    "dbt_installed",
    "inspect_stage5c_project",
    "write_local_stage5c_plan",
]
