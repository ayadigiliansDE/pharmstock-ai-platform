"""Stage 7K.5 online ML decision-runtime contracts and pure helpers.

Stage 7K.5 is deliberately CDC-triggered rather than Kafka-history-dependent. Kafka
identifies the entity whose operational state changed, then the worker performs a
read-through feature assembly from PostgreSQL before calling the Stage 7K champion
API. This avoids cold-start feature corruption after the no-data CDC migration.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Final

from pharmstock.cdc import topic_name

STAGE7K5_VERSION: Final[str] = "0.35.2"
DEFAULT_MODEL_API_URI: Final[str] = "http://localhost:8090"
DEFAULT_CONSUMER_GROUP: Final[str] = "pharmstock-stage7k5-online-v1"
DEFAULT_ALERT_COOLDOWN_SECONDS: Final[int] = 6 * 60 * 60
DEFAULT_MAX_AFFECTED_KEYS: Final[int] = 500
DEFAULT_MAX_EXPIRY_BATCHES_PER_KEY: Final[int] = 100
DEFAULT_MAX_PROCESSING_BACKOFF_SECONDS: Final[int] = 30
DEFAULT_HEARTBEAT_MAX_AGE_SECONDS: Final[int] = 45
DEFAULT_MAX_PENDING_OUTBOX: Final[int] = 1000
DEFAULT_MAX_PENDING_OUTBOX_AGE_SECONDS: Final[int] = 300

DEMAND_FORECAST_TOPIC: Final[str] = "pharmstock.ml.demand_forecasts"
STOCKOUT_PREDICTION_TOPIC: Final[str] = "pharmstock.ml.stockout_predictions"
REORDER_RECOMMENDATION_TOPIC: Final[str] = "pharmstock.ml.reorder_recommendations"
EXPIRY_ALERT_TOPIC: Final[str] = "pharmstock.ml.expiry_alerts"
MODEL_EVENT_TOPIC: Final[str] = "pharmstock.ml.model_events"


@dataclass(frozen=True, slots=True)
class MlOutputTopicSpec:
    name: str
    partitions: int = 3
    replication_factor: int = 1
    cleanup_policy: str = "compact"
    retention_ms: int = 604_800_000

    @property
    def config(self) -> dict[str, str]:
        return {
            "cleanup.policy": self.cleanup_policy,
            "retention.ms": str(self.retention_ms),
        }


ML_OUTPUT_TOPICS: Final[tuple[MlOutputTopicSpec, ...]] = (
    MlOutputTopicSpec(DEMAND_FORECAST_TOPIC),
    MlOutputTopicSpec(STOCKOUT_PREDICTION_TOPIC),
    MlOutputTopicSpec(REORDER_RECOMMENDATION_TOPIC),
    MlOutputTopicSpec(EXPIRY_ALERT_TOPIC),
    MlOutputTopicSpec(MODEL_EVENT_TOPIC, cleanup_policy="delete"),
)

# Only changes that can alter online model inputs are consumed by Stage 7K.5.
MONITORED_CDC_TABLES: Final[tuple[str, ...]] = (
    "pos.demand_attempt",
    "pos.sale_header",
    "pos.sale_line",
    "inventory.stock_batch",
    "inventory.inventory_position",
    "inventory.stock_movement",
    "procurement.supplier",
    "procurement.purchase_order",
    "procurement.purchase_order_line",
)
MONITORED_CDC_TOPICS: Final[tuple[str, ...]] = tuple(
    topic_name(table) for table in MONITORED_CDC_TABLES
)


@dataclass(frozen=True, slots=True)
class CdcChange:
    topic: str
    partition: int
    offset: int
    operation: str
    source_schema: str
    source_table: str
    before: dict[str, Any]
    after: dict[str, Any]
    source_ts_ms: int | None

    @property
    def table(self) -> str:
        return f"{self.source_schema}.{self.source_table}"

    @property
    def row(self) -> dict[str, Any]:
        return self.before if self.operation == "d" else self.after

    @property
    def event_id(self) -> str:
        return source_event_id(self.topic, self.partition, self.offset)


@dataclass(frozen=True, slots=True)
class Stage7K5Config:
    model_api_uri: str
    consumer_group: str
    alert_cooldown_seconds: int
    max_affected_keys: int
    max_expiry_batches_per_key: int
    max_processing_backoff_seconds: int

    def validate(self) -> None:
        if not self.model_api_uri.startswith(("http://", "https://")):
            raise ValueError("PHARMSTOCK_ML_SERVING_URI must be an HTTP(S) URI")
        if not self.consumer_group.strip():
            raise ValueError("PHARMSTOCK_STAGE7K5_CONSUMER_GROUP cannot be empty")
        if self.alert_cooldown_seconds < 0:
            raise ValueError("PHARMSTOCK_STAGE7K5_ALERT_COOLDOWN_SECONDS must be >= 0")
        if self.max_affected_keys < 1:
            raise ValueError("PHARMSTOCK_STAGE7K5_MAX_AFFECTED_KEYS must be >= 1")
        if self.max_expiry_batches_per_key < 1:
            raise ValueError("PHARMSTOCK_STAGE7K5_MAX_EXPIRY_BATCHES_PER_KEY must be >= 1")
        if self.max_processing_backoff_seconds < 1:
            raise ValueError("PHARMSTOCK_STAGE7K5_MAX_PROCESSING_BACKOFF_SECONDS must be >= 1")


def config_from_environment() -> Stage7K5Config:
    config = Stage7K5Config(
        model_api_uri=os.getenv("PHARMSTOCK_ML_SERVING_URI", DEFAULT_MODEL_API_URI).rstrip("/"),
        consumer_group=os.getenv(
            "PHARMSTOCK_STAGE7K5_CONSUMER_GROUP", DEFAULT_CONSUMER_GROUP
        ).strip(),
        alert_cooldown_seconds=int(
            os.getenv(
                "PHARMSTOCK_STAGE7K5_ALERT_COOLDOWN_SECONDS",
                str(DEFAULT_ALERT_COOLDOWN_SECONDS),
            )
        ),
        max_affected_keys=int(
            os.getenv("PHARMSTOCK_STAGE7K5_MAX_AFFECTED_KEYS", str(DEFAULT_MAX_AFFECTED_KEYS))
        ),
        max_expiry_batches_per_key=int(
            os.getenv(
                "PHARMSTOCK_STAGE7K5_MAX_EXPIRY_BATCHES_PER_KEY",
                str(DEFAULT_MAX_EXPIRY_BATCHES_PER_KEY),
            )
        ),
        max_processing_backoff_seconds=int(
            os.getenv(
                "PHARMSTOCK_STAGE7K5_MAX_PROCESSING_BACKOFF_SECONDS",
                str(DEFAULT_MAX_PROCESSING_BACKOFF_SECONDS),
            )
        ),
    )
    config.validate()
    return config


def source_event_id(topic: str, partition: int, offset: int) -> str:
    raw = f"{topic}|{int(partition)}|{int(offset)}".encode()
    return hashlib.sha256(raw).hexdigest()


def prediction_event_id(
    source_id: str,
    model_key: str,
    entity_type: str,
    entity_key: str,
) -> str:
    raw = f"{source_id}|{model_key}|{entity_type}|{entity_key}".encode()
    return hashlib.sha256(raw).hexdigest()


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def decode_debezium_change(
    payload: bytes | str,
    *,
    topic: str,
    partition: int,
    offset: int,
) -> CdcChange:
    """Decode both schemaless and schema-wrapped Kafka Connect JSON envelopes."""

    raw = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    decoded = json.loads(raw)
    if not isinstance(decoded, dict):
        raise ValueError("Debezium value must decode to an object")
    envelope = decoded.get("payload") if isinstance(decoded.get("payload"), dict) else decoded
    operation = str(envelope.get("op", ""))
    if operation not in {"c", "u", "d", "r"}:
        raise ValueError(f"unsupported Debezium operation: {operation!r}")
    source = _object(envelope.get("source"))
    source_schema = str(source.get("schema", ""))
    source_table = str(source.get("table", ""))
    if not source_schema or not source_table:
        raise ValueError("Debezium source schema/table is missing")
    expected = next(
        (table for table in MONITORED_CDC_TABLES if topic_name(table) == topic),
        None,
    )
    actual = f"{source_schema}.{source_table}"
    if expected is None or expected != actual:
        raise ValueError(f"CDC topic/source mismatch: topic={topic!r} source={actual!r}")
    source_ts = source.get("ts_ms")
    if source_ts is None:
        source_ts = envelope.get("ts_ms")
    return CdcChange(
        topic=topic,
        partition=int(partition),
        offset=int(offset),
        operation=operation,
        source_schema=source_schema,
        source_table=source_table,
        before=_object(envelope.get("before")),
        after=_object(envelope.get("after")),
        source_ts_ms=None if source_ts is None else int(source_ts),
    )


def numeric(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def stockout_severity(probability: float, threshold: float, predicted_positive: bool) -> str:
    """Translate calibrated rare-event risk into an operational severity band.

    Absolute probabilities are intentionally not used because the trained stockout
    prevalence is extremely low. Severity is expressed as multiples of the
    validation-selected operating threshold.
    """

    probability = max(numeric(probability), 0.0)
    threshold = max(numeric(threshold), 1e-9)
    if not predicted_positive:
        return "NORMAL"
    ratio = probability / threshold
    if ratio >= 8.0:
        return "CRITICAL"
    if ratio >= 4.0:
        return "HIGH"
    if ratio >= 2.0:
        return "MEDIUM"
    return "WATCH"


SEVERITY_RANK: Final[dict[str, int]] = {
    "NORMAL": 0,
    "WATCH": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}


def alert_is_actionable(
    *,
    predicted_positive: bool,
    severity: str,
    previous_severity: str | None,
    previous_alert_at: datetime | None,
    now: datetime,
    cooldown_seconds: int,
) -> bool:
    if not predicted_positive:
        return False
    previous_rank = SEVERITY_RANK.get(previous_severity or "NORMAL", 0)
    current_rank = SEVERITY_RANK.get(severity, 0)
    if current_rank > previous_rank:
        return True
    if previous_alert_at is None:
        return True
    if previous_alert_at.tzinfo is None:
        previous_alert_at = previous_alert_at.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return (now - previous_alert_at).total_seconds() >= max(cooldown_seconds, 0)


def stage7k5_contract() -> dict[str, object]:
    return {
        "stage": "7K.5",
        "version": STAGE7K5_VERSION,
        "runtime": "CDC_TRIGGERED_POSTGRES_READ_THROUGH_INFERENCE",
        "cold_start_policy": "NO_KAFKA_HISTORY_DEPENDENCY",
        "source_of_truth": "POSTGRESQL_OPERATIONAL_STATE",
        "cdc_trigger_topics": list(MONITORED_CDC_TOPICS),
        "output_topics": [asdict(item) for item in ML_OUTPUT_TOPICS],
        "models": [
            "demand_forecast",
            "stockout_risk",
            "reorder_recommendation",
            "expiry_slow_moving_risk",
        ],
        "delivery": {
            "source_offsets": "MANUAL_COMMIT_AFTER_DURABLE_DECISION_AND_OUTBOX_PUBLISH",
            "idempotency": "TOPIC_PARTITION_OFFSET_SHA256",
            "prediction_outbox": True,
            "cross_system_exactly_once_claimed": False,
            "downstream_dedupe_key": "prediction_event_id",
        },
        "reliability": {
            "docker_healthcheck": True,
            "durable_invalid_cdc_quarantine": True,
            "processing_retry": "BOUNDED_EXPONENTIAL_BACKOFF",
            "heartbeat_max_age_seconds": DEFAULT_HEARTBEAT_MAX_AGE_SECONDS,
            "max_pending_outbox": DEFAULT_MAX_PENDING_OUTBOX,
            "max_pending_outbox_age_seconds": DEFAULT_MAX_PENDING_OUTBOX_AGE_SECONDS,
        },
        "alerting": {
            "stockout_cooldown_seconds": DEFAULT_ALERT_COOLDOWN_SECONDS,
            "severity_basis": "MULTIPLE_OF_MODEL_OPERATING_THRESHOLD",
            "severity_escalation_bypasses_cooldown": True,
        },
        "cloud_mutation": False,
        "bigquery_write": False,
        "model_retraining_per_event": False,
    }
