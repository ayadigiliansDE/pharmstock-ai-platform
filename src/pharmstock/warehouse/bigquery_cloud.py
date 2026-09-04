"""Cloud-safe BigQuery deployment planning for Stage 5B.

The module intentionally has no import-time dependency on google-cloud-bigquery so the
normal application/test path stays local and lightweight. Google client imports belong in
the explicit cloud execution script only.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pharmstock.warehouse.bigquery_contracts import (
    DEFAULT_DATASET_ID,
    DEFAULT_LOCATION,
    TABLE_CONTRACTS,
)

_PROJECT_PLACEHOLDERS: Final[frozenset[str]] = frozenset({"", "YOUR_PROJECT_ID", "your-project-id"})
_DATASET_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")


@dataclass(frozen=True, slots=True)
class BigQueryCloudConfig:
    project_id: str | None
    dataset_id: str
    location: str

    @property
    def project_configured(self) -> bool:
        return bool(self.project_id and self.project_id not in _PROJECT_PLACEHOLDERS)


@dataclass(frozen=True, slots=True)
class BigQueryLocalTable:
    table_name: str
    parquet_files: tuple[Path, ...]
    expected_rows: int


@dataclass(frozen=True, slots=True)
class BigQueryReadiness:
    local_ready: bool
    client_installed: bool
    project_configured: bool
    credential_hint_present: bool
    dataset_id_valid: bool
    table_count: int
    total_expected_rows: int
    issues: tuple[str, ...]

    @property
    def cloud_preconditions_present(self) -> bool:
        return (
            self.local_ready
            and self.client_installed
            and self.project_configured
            and self.credential_hint_present
            and self.dataset_id_valid
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "local_ready": self.local_ready,
            "client_installed": self.client_installed,
            "project_configured": self.project_configured,
            "credential_hint_present": self.credential_hint_present,
            "dataset_id_valid": self.dataset_id_valid,
            "cloud_preconditions_present": self.cloud_preconditions_present,
            "table_count": self.table_count,
            "total_expected_rows": self.total_expected_rows,
            "issues": list(self.issues),
        }


def cloud_config_from_environment() -> BigQueryCloudConfig:
    project = os.getenv("PHARMSTOCK_BQ_PROJECT")
    project = project.strip() if project else None
    dataset = os.getenv("PHARMSTOCK_BQ_DATASET", DEFAULT_DATASET_ID).strip() or DEFAULT_DATASET_ID
    location = os.getenv("PHARMSTOCK_BQ_LOCATION", DEFAULT_LOCATION).strip() or DEFAULT_LOCATION
    return BigQueryCloudConfig(project, dataset, location)


def bigquery_client_installed() -> bool:
    try:
        return importlib.util.find_spec("google.cloud.bigquery") is not None
    except (ImportError, ModuleNotFoundError):
        return False



def adc_credential_hint_present() -> bool:
    explicit = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if explicit:
        return Path(explicit).expanduser().is_file()

    candidates: list[Path] = []
    appdata = os.getenv("APPDATA", "").strip()
    if appdata:
        candidates.append(Path(appdata) / "gcloud" / "application_default_credentials.json")
    candidates.append(Path.home() / ".config" / "gcloud" / "application_default_credentials.json")
    return any(path.is_file() for path in candidates)


def _stage5a_table_counts(stage5a_root: Path) -> dict[str, int]:
    summary_path = stage5a_root / "spark_export_summary.json"
    if not summary_path.exists():
        raise RuntimeError(f"missing Stage 5A Spark summary: {summary_path}")
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    tables = payload.get("tables")
    if not isinstance(tables, dict):
        raise RuntimeError("Stage 5A Spark summary has no table map")
    return {
        str(name): int(details["exported_rows"])
        for name, details in tables.items()
        if isinstance(details, dict)
    }


def discover_local_warehouse(stage5a_root: Path) -> tuple[BigQueryLocalTable, ...]:
    if not (stage5a_root / "_SUCCESS").exists():
        raise RuntimeError("Stage 5B requires a completed Stage 5A checkpoint")
    expected = _stage5a_table_counts(stage5a_root)
    tables: list[BigQueryLocalTable] = []
    for table_name in TABLE_CONTRACTS:
        root = stage5a_root / "warehouse_ready" / table_name
        files = tuple(sorted(path for path in root.rglob("*.parquet") if path.is_file()))
        if table_name not in expected:
            raise RuntimeError(f"Stage 5A summary missing expected rows for {table_name}")
        expected_rows = expected[table_name]
        if expected_rows > 0 and not files:
            raise RuntimeError(f"no Stage 5A Parquet files for non-empty {table_name}")
        tables.append(BigQueryLocalTable(table_name, files, expected_rows))
    return tuple(tables)


def assess_bigquery_readiness(
    stage5a_root: Path,
    config: BigQueryCloudConfig | None = None,
    *,
    client_installed: bool | None = None,
    credential_hint_present: bool | None = None,
) -> BigQueryReadiness:
    config = config or cloud_config_from_environment()
    issues: list[str] = []
    try:
        tables = discover_local_warehouse(stage5a_root)
        local_ready = True
    except RuntimeError as exc:
        tables = ()
        local_ready = False
        issues.append(str(exc))

    installed = bigquery_client_installed() if client_installed is None else client_installed
    credential_hint = (
        adc_credential_hint_present()
        if credential_hint_present is None
        else credential_hint_present
    )
    if not installed:
        issues.append('optional BigQuery client not installed; use pip install -e ".[gcp]"')
    if not config.project_configured:
        issues.append("PHARMSTOCK_BQ_PROJECT is not configured")
    if not credential_hint:
        issues.append("no local ADC credential hint detected")
    dataset_valid = bool(_DATASET_PATTERN.fullmatch(config.dataset_id))
    if not dataset_valid:
        issues.append(f"invalid BigQuery dataset id: {config.dataset_id!r}")

    return BigQueryReadiness(
        local_ready=local_ready,
        client_installed=installed,
        project_configured=config.project_configured,
        credential_hint_present=credential_hint,
        dataset_id_valid=dataset_valid,
        table_count=len(tables),
        total_expected_rows=sum(table.expected_rows for table in tables),
        issues=tuple(issues),
    )


def write_stage5b_local_plan(
    output_root: Path,
    stage5a_root: Path,
    config: BigQueryCloudConfig | None = None,
) -> dict[str, object]:
    config = config or cloud_config_from_environment()
    tables = discover_local_warehouse(stage5a_root)
    readiness = assess_bigquery_readiness(stage5a_root, config)
    output_root.mkdir(parents=True, exist_ok=True)

    plan: dict[str, object] = {
        "stage": "5B",
        "mode": "local_safe_preflight",
        "cloud_mutation": False,
        "project_id": config.project_id,
        "dataset_id": config.dataset_id,
        "location": config.location,
        "readiness": readiness.to_dict(),
        "deployment_strategy": {
            "load": "local Parquet -> per-table BigQuery staging table",
            "verification": (
                "staging row count must equal Stage 5A expected rows; "
                "REQUIRED fields must be non-null"
            ),
            "promotion": (
                "CREATE OR REPLACE target with explicit NOT NULL contract from verified staging"
            ),
            "cleanup": "delete staging table after verified promotion",
            "target_guard": "existing target schema/partition/clustering must match contract",
        },
        "tables": [
            {
                "table_name": table.table_name,
                "expected_rows": table.expected_rows,
                "parquet_files": [str(path) for path in table.parquet_files],
                "partition_field": TABLE_CONTRACTS[table.table_name].partition_field,
                "clustering_fields": list(
                    TABLE_CONTRACTS[table.table_name].clustering_fields
                ),
            }
            for table in tables
        ],
    }
    (output_root / "cloud_readiness.json").write_text(
        json.dumps(readiness.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
    )
    (output_root / "deployment_plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8"
    )
    return plan


__all__ = [
    "BigQueryCloudConfig",
    "BigQueryLocalTable",
    "BigQueryReadiness",
    "adc_credential_hint_present",
    "assess_bigquery_readiness",
    "bigquery_client_installed",
    "cloud_config_from_environment",
    "discover_local_warehouse",
    "write_stage5b_local_plan",
]
