"""Stage 5D dbt master-dimension contract and readiness checks."""

from __future__ import annotations

import importlib.util
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pharmstock.analytics.dbt_stage import DBT_PROFILES_RELATIVE, DBT_PROJECT_RELATIVE

MASTER_STAGING_MODELS: Final[tuple[str, ...]] = (
    "stg_master_product",
    "stg_master_organization",
    "stg_master_branch",
    "stg_master_supplier",
)

DIMENSION_MODELS: Final[tuple[str, ...]] = (
    "dim_product",
    "dim_branch",
    "dim_supplier",
)

STAGE5D_RELATIONSHIP_TESTS: Final[tuple[str, ...]] = (
    "assert_branch_dimension_organization_fk",
    "assert_sales_products_have_dimension",
    "assert_inventory_products_have_dimension",
    "assert_operational_branches_have_dimension",
    "assert_procurement_suppliers_have_dimension",
)


@dataclass(frozen=True, slots=True)
class DimensionStage5DReadiness:
    dbt_installed: bool
    project_configured: bool
    master_dataset_configured: bool
    stage5d_cloud_report_present: bool
    master_staging_model_count: int
    dimension_model_count: int
    relationship_test_count: int
    project_files_ready: bool
    issues: tuple[str, ...]

    @property
    def cloud_ready_hint(self) -> bool:
        return (
            self.dbt_installed
            and self.project_configured
            and self.master_dataset_configured
            and self.stage5d_cloud_report_present
            and self.project_files_ready
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "dbt_installed": self.dbt_installed,
            "project_configured": self.project_configured,
            "master_dataset_configured": self.master_dataset_configured,
            "stage5d_cloud_report_present": self.stage5d_cloud_report_present,
            "master_staging_model_count": self.master_staging_model_count,
            "dimension_model_count": self.dimension_model_count,
            "relationship_test_count": self.relationship_test_count,
            "project_files_ready": self.project_files_ready,
            "cloud_ready_hint": self.cloud_ready_hint,
            "issues": list(self.issues),
        }


def _dbt_installed() -> bool:
    try:
        return importlib.util.find_spec("dbt.cli.main") is not None
    except (ImportError, ModuleNotFoundError):
        return False


def inspect_stage5d_dimensions(
    project_root: Path = DBT_PROJECT_RELATIVE,
    stage5d_root: Path = Path("artifacts/stage5d"),
    *,
    installed: bool | None = None,
) -> DimensionStage5DReadiness:
    issues: list[str] = []
    master_staging = tuple(
        sorted(path.stem for path in (project_root / "models/master_staging").glob("*.sql"))
    )
    dimensions = tuple(
        sorted(path.stem for path in (project_root / "models/dimensions").glob("*.sql"))
    )
    test_root = project_root / "tests"
    tests = {path.stem for path in test_root.glob("*.sql")}
    present_relationship_tests = tuple(
        name for name in STAGE5D_RELATIONSHIP_TESTS if name in tests
    )

    if set(master_staging) != set(MASTER_STAGING_MODELS):
        issues.append("Stage 5D master staging model set does not match contract")
    if set(dimensions) != set(DIMENSION_MODELS):
        issues.append("Stage 5D dimension model set does not match contract")
    if set(present_relationship_tests) != set(STAGE5D_RELATIONSHIP_TESTS):
        issues.append("Stage 5D relationship test set does not match contract")

    required_files = (
        project_root / "models/master_staging/_master_sources.yml",
        project_root / "models/dimensions/_dimensions.yml",
        DBT_PROFILES_RELATIVE / "profiles.yml",
    )
    if any(not path.is_file() for path in required_files):
        issues.append("Stage 5D dbt project files are incomplete")

    installed_value = _dbt_installed() if installed is None else installed
    if not installed_value:
        issues.append("dbt is not installed")
    project_configured = bool(os.getenv("PHARMSTOCK_BQ_PROJECT", "").strip())
    if not project_configured:
        issues.append("PHARMSTOCK_BQ_PROJECT is not configured")
    master_dataset = os.getenv("PHARMSTOCK_BQ_MASTER_DATASET", "pharmstock_master").strip()
    master_dataset_configured = bool(master_dataset)
    if not master_dataset_configured:
        issues.append("PHARMSTOCK_BQ_MASTER_DATASET is empty")

    cloud_report = stage5d_root / "cloud_execution_report.json"
    cloud_present = cloud_report.is_file()
    if cloud_present:
        report = json.loads(cloud_report.read_text(encoding="utf-8"))
        if report.get("cloud_mutation") is not True:
            issues.append("Stage 5D cloud execution report is not successful")
    else:
        issues.append("Stage 5D cloud execution report is not present")

    files_ready = (
        set(master_staging) == set(MASTER_STAGING_MODELS)
        and set(dimensions) == set(DIMENSION_MODELS)
        and set(present_relationship_tests) == set(STAGE5D_RELATIONSHIP_TESTS)
        and all(path.is_file() for path in required_files)
    )
    return DimensionStage5DReadiness(
        dbt_installed=installed_value,
        project_configured=project_configured,
        master_dataset_configured=master_dataset_configured,
        stage5d_cloud_report_present=cloud_present,
        master_staging_model_count=len(master_staging),
        dimension_model_count=len(dimensions),
        relationship_test_count=len(present_relationship_tests),
        project_files_ready=files_ready,
        issues=tuple(issues),
    )


__all__ = [
    "DIMENSION_MODELS",
    "MASTER_STAGING_MODELS",
    "STAGE5D_RELATIONSHIP_TESTS",
    "DimensionStage5DReadiness",
    "inspect_stage5d_dimensions",
]
