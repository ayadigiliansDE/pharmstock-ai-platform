"""Stage 7I contracts for storage-safe continuous CDC into BigQuery Sandbox.

Stage 7H is the immutable historical baseline. Stage 7I only appends compact
Debezium change events and exposes zero-storage current-state views. This avoids
BigQuery Sandbox DML/streaming restrictions and, critically, avoids copying the
31.9M-row baseline during incremental processing.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pharmstock.rebuild.contracts import SNAPSHOT_TABLES, validate_offset_range

STAGE7I_ROOT: Final[Path] = Path("artifacts/stage7i")
STAGE7H_SUCCESS: Final[Path] = Path("artifacts/stage7h/_SUCCESS")
STAGE7G_RESUME_OFFSETS: Final[Path] = Path("artifacts/stage7g/cdc_resume_offsets.json")
STAGE7I_RESUME_OFFSETS: Final[Path] = STAGE7I_ROOT / "resume_offsets.json"
DEFAULT_DELTA_DATASET: Final[str] = "pharmstock_cdc_delta"
DEFAULT_CURRENT_DATASET: Final[str] = "pharmstock_ops_current"
DEFAULT_EVENTS_TABLE: Final[str] = "events"
DEFAULT_WARN_GIB: Final[float] = 8.2
DEFAULT_HARD_STOP_GIB: Final[float] = 8.5
SANDBOX_LIMIT_GIB: Final[float] = 10.0
DEFAULT_MAX_BATCH_RECORDS: Final[int] = 50_000
DEFAULT_WATCH_INTERVAL_SECONDS: Final[int] = 60
DEFAULT_PARQUET_EXPANSION_FACTOR: Final[float] = 6.0

CDC_SNAPSHOT_TABLES: Final[tuple[str, ...]] = tuple(
    spec.source_table for spec in SNAPSHOT_TABLES if spec.cdc_managed
)


@dataclass(frozen=True, slots=True)
class Stage7IConfig:
    """Runtime configuration for one Stage 7I CDC worker."""

    project_id: str | None
    raw_dataset: str
    delta_dataset: str
    current_dataset: str
    location: str
    warn_gib: float
    hard_stop_gib: float
    max_batch_records: int
    parquet_expansion_factor: float

    @property
    def project_configured(self) -> bool:
        return bool(self.project_id and self.project_id.strip())

    def validate(self) -> None:
        if not self.project_configured:
            raise ValueError("PHARMSTOCK_BQ_PROJECT cannot be empty")
        if not (0 < self.warn_gib < self.hard_stop_gib < SANDBOX_LIMIT_GIB):
            raise ValueError(
                "storage thresholds must satisfy 0 < warn < hard_stop < 10 GiB"
            )
        if self.max_batch_records <= 0:
            raise ValueError("max_batch_records must be positive")
        if self.parquet_expansion_factor < 1:
            raise ValueError("parquet_expansion_factor must be >= 1")


def config_from_environment() -> Stage7IConfig:
    config = Stage7IConfig(
        project_id=os.getenv("PHARMSTOCK_BQ_PROJECT", "").strip() or None,
        raw_dataset=os.getenv("PHARMSTOCK_BQ_REBUILD_DATASET", "pharmstock_ops_rebuild").strip(),
        delta_dataset=os.getenv("PHARMSTOCK_BQ_CDC_DATASET", DEFAULT_DELTA_DATASET).strip(),
        current_dataset=os.getenv("PHARMSTOCK_BQ_CURRENT_DATASET", DEFAULT_CURRENT_DATASET).strip(),
        location=os.getenv("PHARMSTOCK_BQ_LOCATION", "EU").strip(),
        warn_gib=float(os.getenv("PHARMSTOCK_BQ_WARN_GIB", str(DEFAULT_WARN_GIB))),
        hard_stop_gib=float(
            os.getenv("PHARMSTOCK_BQ_HARD_STOP_GIB", str(DEFAULT_HARD_STOP_GIB))
        ),
        max_batch_records=int(
            os.getenv("PHARMSTOCK_CDC_MAX_BATCH_RECORDS", str(DEFAULT_MAX_BATCH_RECORDS))
        ),
        parquet_expansion_factor=float(
            os.getenv(
                "PHARMSTOCK_CDC_PARQUET_EXPANSION_FACTOR",
                str(DEFAULT_PARQUET_EXPANSION_FACTOR),
            )
        ),
    )
    return config


def read_offsets(path: Path) -> dict[str, dict[str, int]]:
    """Read persisted offsets, allowing a legacy subset during topic migrations."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload:
        raise ValueError(f"invalid offsets payload: {path}")
    offsets: dict[str, dict[str, int]] = {}
    for topic, parts in payload.items():
        if not isinstance(parts, dict) or not parts:
            raise ValueError(f"invalid offsets payload: {path}")
        normalized_parts: dict[str, int] = {}
        for partition, offset in parts.items():
            partition_text = str(partition)
            offset_value = int(offset)
            if not partition_text.isdigit() or offset_value < 0:
                raise ValueError(
                    f"invalid CDC offset {topic}:{partition_text}={offset_value}"
                )
            normalized_parts[partition_text] = offset_value
        offsets[str(topic)] = normalized_parts
    return offsets


def normalize_resume_offsets(
    existing: dict[str, dict[str, int]],
    low: dict[str, dict[str, int]],
    high: dict[str, dict[str, int]],
) -> tuple[dict[str, dict[str, int]], tuple[str, ...]]:
    """Upgrade legacy offset sets when canonical CDC topics are added.

    Missing topics start at the Kafka low watermark, not the high watermark. With
    Debezium snapshot.mode=no_data this captures every retained event emitted after
    the table joined the publication while never replaying the historical database.
    """

    validate_offset_range(low, high)
    unknown = sorted(set(existing) - set(high))
    if unknown:
        raise ValueError(f"legacy CDC offsets contain unknown topics: {unknown}")

    normalized: dict[str, dict[str, int]] = {}
    added: list[str] = []
    for topic, high_parts in high.items():
        low_parts = low[topic]
        if topic not in existing:
            normalized[topic] = {
                partition: int(low_parts[partition]) for partition in high_parts
            }
            added.append(topic)
            continue
        parts = existing[topic]
        if set(parts) != set(high_parts):
            raise ValueError(f"partition mismatch for {topic}")
        normalized[topic] = {partition: int(parts[partition]) for partition in high_parts}

    validate_offset_range(normalized, high)
    return normalized, tuple(sorted(added))


def write_offsets_atomic(path: Path, offsets: dict[str, dict[str, int]]) -> None:
    validate_offset_range(offsets, offsets)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(offsets, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def initial_resume_offsets() -> tuple[Path, dict[str, dict[str, int]]]:
    if STAGE7I_RESUME_OFFSETS.is_file():
        return STAGE7I_RESUME_OFFSETS, read_offsets(STAGE7I_RESUME_OFFSETS)
    if not STAGE7G_RESUME_OFFSETS.is_file():
        raise FileNotFoundError(
            "Stage 7I requires artifacts/stage7g/cdc_resume_offsets.json"
        )
    return STAGE7G_RESUME_OFFSETS, read_offsets(STAGE7G_RESUME_OFFSETS)


def capped_end_offsets(
    start: dict[str, dict[str, int]],
    high: dict[str, dict[str, int]],
    max_records: int,
) -> dict[str, dict[str, int]]:
    """Fairly cap one deterministic micro-batch across all active partitions."""

    validate_offset_range(start, high)
    if max_records <= 0:
        raise ValueError("max_records must be positive")

    active: list[tuple[str, str, int]] = []
    end = {
        topic: {partition: int(offset) for partition, offset in partitions.items()}
        for topic, partitions in start.items()
    }
    for topic in sorted(start):
        for partition in sorted(start[topic], key=int):
            backlog = int(high[topic][partition]) - int(start[topic][partition])
            if backlog > 0:
                active.append((topic, partition, backlog))

    if not active:
        return end

    remaining = max_records
    pending = active[:]
    # Water-fill active partitions so a hot early-sorted partition cannot starve
    # all later topics forever.
    while remaining > 0 and pending:
        fair_share = max(1, remaining // len(pending))
        next_pending: list[tuple[str, str, int]] = []
        progressed = 0
        for topic, partition, backlog in pending:
            if remaining <= 0:
                next_pending.append((topic, partition, backlog))
                continue
            take = min(backlog, fair_share, remaining)
            end[topic][partition] += take
            remaining -= take
            progressed += take
            backlog -= take
            if backlog > 0:
                next_pending.append((topic, partition, backlog))
        if progressed == 0:
            break
        pending = next_pending

    expected = validate_offset_range(start, end)
    if expected > max_records:
        raise AssertionError("micro-batch cap exceeded")
    return end


def batch_id_for_offsets(
    start: dict[str, dict[str, int]], end: dict[str, dict[str, int]]
) -> str:
    validate_offset_range(start, end)
    canonical = json.dumps(
        {"start": start, "end": end},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:20]


def projected_storage_gib(
    current_bytes: int,
    parquet_bytes: int,
    expansion_factor: float = DEFAULT_PARQUET_EXPANSION_FACTOR,
) -> float:
    if current_bytes < 0 or parquet_bytes < 0:
        raise ValueError("storage byte counts cannot be negative")
    if expansion_factor < 1:
        raise ValueError("expansion_factor must be >= 1")
    projected = current_bytes + math.ceil(parquet_bytes * expansion_factor)
    return projected / (1024**3)


def storage_guard_status(current_gib: float, projected_gib: float, config: Stage7IConfig) -> str:
    if current_gib >= config.hard_stop_gib or projected_gib >= config.hard_stop_gib:
        return "STOP"
    if current_gib >= config.warn_gib or projected_gib >= config.warn_gib:
        return "WARN"
    return "SAFE"


def json_scalar_path(field_name: str) -> str:
    escaped = field_name.replace("\\", "\\\\").replace('"', '\\"')
    return f'$."{escaped}"'


def json_cast_expression(field_name: str, field_type: str, source_alias: str = "l") -> str:
    """Render a BigQuery expression that restores a Debezium JSON scalar."""

    path = json_scalar_path(field_name)
    value = f"JSON_VALUE({source_alias}.after_json, '{path}')"
    normalized = field_type.upper()
    if normalized in {"STRING"}:
        return value
    if normalized in {"INTEGER", "INT64"}:
        return f"SAFE_CAST({value} AS INT64)"
    if normalized in {"FLOAT", "FLOAT64"}:
        return f"SAFE_CAST({value} AS FLOAT64)"
    if normalized in {"NUMERIC", "DECIMAL"}:
        return f"SAFE_CAST({value} AS NUMERIC)"
    if normalized in {"BIGNUMERIC", "BIGDECIMAL"}:
        return f"SAFE_CAST({value} AS BIGNUMERIC)"
    if normalized in {"BOOLEAN", "BOOL"}:
        return f"SAFE_CAST({value} AS BOOL)"
    if normalized == "DATE":
        numeric = f"SAFE_CAST({value} AS INT64)"
        return (
            f"COALESCE(SAFE_CAST({value} AS DATE), "
            f"DATE_FROM_UNIX_DATE({numeric}))"
        )
    if normalized == "TIMESTAMP":
        numeric = f"SAFE_CAST({value} AS INT64)"
        return (
            f"COALESCE(SAFE_CAST({value} AS TIMESTAMP), "
            f"IF(ABS({numeric}) >= 100000000000000, "
            f"TIMESTAMP_MICROS({numeric}), TIMESTAMP_MILLIS({numeric})))"
        )
    if normalized == "DATETIME":
        return f"SAFE_CAST({value} AS DATETIME)"
    if normalized == "TIME":
        return f"SAFE_CAST({value} AS TIME)"
    if normalized == "BYTES":
        return f"SAFE.FROM_BASE64({value})"
    raise ValueError(f"Stage 7I does not support BigQuery field type {field_type!r}")


def current_state_view_sql(
    *,
    project_id: str,
    raw_dataset: str,
    delta_dataset: str,
    current_dataset: str,
    source_table: str,
    primary_key: tuple[str, ...],
    fields: tuple[tuple[str, str], ...],
) -> str:
    """Build a zero-storage current-state overlay view for one CDC table."""

    if not primary_key:
        raise ValueError("primary_key cannot be empty")
    schema_name, table_name = source_table.split(".", 1)
    raw_table = f"{project_id}.{raw_dataset}.{schema_name}__{table_name}"
    delta_table = f"{project_id}.{delta_dataset}.{DEFAULT_EVENTS_TABLE}"
    view_table = f"{project_id}.{current_dataset}.{schema_name}__{table_name}"

    key_partition = ", ".join(
        f"JSON_VALUE(key_json, '{json_scalar_path(key)}')" for key in primary_key
    )
    joins = " AND ".join(
        f"CAST(b.`{key}` AS STRING) = JSON_VALUE(l.key_json, "
        f"'{json_scalar_path(key)}')"
        for key in primary_key
    )
    selected_fields = ",\n      ".join(
        f"{json_cast_expression(name, field_type)} AS `{name}`" for name, field_type in fields
    )

    return f"""CREATE OR REPLACE VIEW `{view_table}` AS
WITH event_dedup AS (
  SELECT *
  FROM `{delta_table}`
  WHERE source_schema = '{schema_name}' AND source_table = '{table_name}'
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY event_id
    ORDER BY ingested_at DESC
  ) = 1
),
latest AS (
  SELECT *
  FROM event_dedup
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY {key_partition}
    ORDER BY COALESCE(source_lsn, -1) DESC, `partition` DESC, `offset` DESC
  ) = 1
),
base_retained AS (
  SELECT b.*
  FROM `{raw_table}` AS b
  LEFT JOIN latest AS l
    ON {joins}
  WHERE l.event_id IS NULL
),
upserts AS (
  SELECT
      {selected_fields}
  FROM latest AS l
  WHERE l.op != 'd'
)
SELECT * FROM base_retained
UNION ALL
SELECT * FROM upserts"""


def passthrough_view_sql(
    *, project_id: str, raw_dataset: str, current_dataset: str, source_table: str
) -> str:
    schema_name, table_name = source_table.split(".", 1)
    raw_table = f"{project_id}.{raw_dataset}.{schema_name}__{table_name}"
    view_table = f"{project_id}.{current_dataset}.{schema_name}__{table_name}"
    return f"CREATE OR REPLACE VIEW `{view_table}` AS SELECT * FROM `{raw_table}`"


def stage7i_contract() -> dict[str, object]:
    return {
        "stage": "7I",
        "flow": "POSTGRESQL -> DEBEZIUM -> KAFKA -> SPARK MICRO_BATCH -> BIGQUERY APPEND DELTA",
        "baseline": "STAGE_7H_IMMUTABLE_RAW_31_954_735_ROWS",
        "cdc_tables": list(CDC_SNAPSHOT_TABLES),
        "bigquery_sandbox_strategy": {
            "streaming_api": False,
            "dml_merge": False,
            "append_only_load_jobs": True,
            "current_state_views": True,
            "raw_baseline_copy": False,
            "temporary_full_table_copy": False,
        },
        "storage_guard": {
            "warn_gib": DEFAULT_WARN_GIB,
            "hard_stop_gib": DEFAULT_HARD_STOP_GIB,
            "sandbox_limit_gib": SANDBOX_LIMIT_GIB,
            "check_before_every_cloud_batch": True,
        },
        "offset_semantics": {
            "initial_offsets": "artifacts/stage7g/cdc_resume_offsets.json",
            "committed_offsets": "artifacts/stage7i/resume_offsets.json",
            "advance_only_after_bigquery_verification": True,
            "historical_kafka_replay": False,
        },
    }
