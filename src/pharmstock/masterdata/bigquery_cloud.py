"""BigQuery deployment helpers for Stage 5D master-data snapshots."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pharmstock.masterdata.stage5d import (
    BIGQUERY_CLUSTER_FIELDS,
    BIGQUERY_SCHEMAS,
    MASTER_PRIMARY_KEYS,
    MASTER_TABLES,
)

BQ_TYPE_SQL: Final[dict[str, str]] = {
    "STRING": "STRING",
    "INTEGER": "INT64",
    "FLOAT": "FLOAT64",
    "BOOLEAN": "BOOL",
}


@dataclass(frozen=True, slots=True)
class MasterLoadPlan:
    project_id: str
    dataset_id: str
    location: str
    table_counts: dict[str, int]
    snapshot_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "dataset_id": self.dataset_id,
            "location": self.location,
            "table_counts": dict(self.table_counts),
            "snapshot_id": self.snapshot_id,
            "tables": list(MASTER_TABLES),
        }


def load_plan_from_snapshot(
    *, snapshot_root: Path, project_id: str, dataset_id: str, location: str
) -> MasterLoadPlan:
    manifest_path = snapshot_root / "master_snapshot_manifest.json"
    if not manifest_path.is_file() or not (snapshot_root / "_SUCCESS").is_file():
        raise RuntimeError("Completed Stage 5D local master snapshot is required")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    counts = {name: int(manifest["table_counts"][name]) for name in MASTER_TABLES}
    for table, count in counts.items():
        source = snapshot_root / "master_ready" / f"{table}.csv"
        if not source.is_file():
            raise RuntimeError(f"Stage 5D master file is missing: {source}")
        if count <= 0:
            raise RuntimeError(f"Stage 5D master table must be non-empty: {table}")
    return MasterLoadPlan(
        project_id=project_id,
        dataset_id=dataset_id,
        location=location,
        table_counts=counts,
        snapshot_id=str(manifest["snapshot_id"]),
    )


def final_table_ddl(project_id: str, dataset_id: str, table: str, staging_id: str) -> str:
    if table not in MASTER_TABLES:
        raise KeyError(table)
    columns = []
    for name, field_type, mode in BIGQUERY_SCHEMAS[table]:
        nullable = " NOT NULL" if mode == "REQUIRED" else ""
        columns.append(f"  `{name}` {BQ_TYPE_SQL[field_type]}{nullable}")
    cluster = BIGQUERY_CLUSTER_FIELDS[table]
    cluster_sql = f"\nCLUSTER BY {', '.join(f'`{item}`' for item in cluster)}" if cluster else ""
    final_id = f"{project_id}.{dataset_id}.{table}"
    return (
        f"CREATE OR REPLACE TABLE `{final_id}` (\n"
        + ",\n".join(columns)
        + f"\n){cluster_sql}\nAS SELECT * FROM `{staging_id}`"
    )


def required_fields(table: str) -> tuple[str, ...]:
    return tuple(name for name, _, mode in BIGQUERY_SCHEMAS[table] if mode == "REQUIRED")


def null_violation_sql(staging_id: str, table: str) -> str:
    required = required_fields(table)
    predicates = " OR ".join(f"`{field}` IS NULL" for field in required)
    return f"SELECT COUNT(*) AS violation_count FROM `{staging_id}` WHERE {predicates}"


def duplicate_primary_key_sql(table_id: str, table: str) -> str:
    key = MASTER_PRIMARY_KEYS[table]
    return (
        "SELECT COUNT(*) AS duplicate_groups FROM ("
        f"SELECT `{key}` FROM `{table_id}` GROUP BY `{key}` HAVING COUNT(*) > 1)"
    )


__all__ = [
    "BQ_TYPE_SQL",
    "MasterLoadPlan",
    "duplicate_primary_key_sql",
    "final_table_ddl",
    "load_plan_from_snapshot",
    "null_violation_sql",
    "required_fields",
]
