"""Pure-Python contract for the Stage 4A Kafka -> Bronze boundary.

Spark implements the same envelope checks with DataFrame expressions. Keeping this
small validator free from PySpark lets the normal project test suite verify the
analytics contract without installing Spark into the application virtualenv.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

SALES_TOPIC = "pharmstock.sales.v1"
INVENTORY_TOPIC = "pharmstock.inventory.v1"
PROCUREMENT_TOPIC = "pharmstock.procurement.v1"

BRONZE_TOPICS = (SALES_TOPIC, INVENTORY_TOPIC, PROCUREMENT_TOPIC)
BRONZE_EVENT_TOPICS: dict[str, str] = {
    "sale.units_fulfilled": SALES_TOPIC,
    "inventory.quantity_changed": INVENTORY_TOPIC,
    "inventory.reorder_required": INVENTORY_TOPIC,
    "purchase_order.created": PROCUREMENT_TOPIC,
    "goods_receipt.received": PROCUREMENT_TOPIC,
    "restock.applied": PROCUREMENT_TOPIC,
}
SUPPORTED_SCHEMA_VERSION = "1.0"
_UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


@dataclass(frozen=True, slots=True)
class BronzeEnvelopeValidation:
    is_valid: bool
    error: str | None
    event_type: str | None = None
    event_id: str | None = None


def _aware_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _uuid_text(value: Any) -> bool:
    if not isinstance(value, str) or not _UUID_PATTERN.fullmatch(value):
        return False
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def validate_bronze_envelope(
    payload: bytes | bytearray | memoryview,
    *,
    topic: str,
    key: bytes | None,
) -> BronzeEnvelopeValidation:
    """Validate only the common transport envelope required for Bronze ingestion.

    Event-specific payload semantics remain owned by the domain/Stage 3 validation
    path. Bronze deliberately preserves the raw payload for later Silver parsing.
    """

    try:
        decoded = json.loads(bytes(payload).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return BronzeEnvelopeValidation(False, "malformed_json")
    if not isinstance(decoded, dict):
        return BronzeEnvelopeValidation(False, "json_not_object")

    event_type = decoded.get("event_type")
    event_id = decoded.get("event_id")
    if not _uuid_text(event_id):
        return BronzeEnvelopeValidation(False, "invalid_event_id", event_type, event_id)
    if event_type not in BRONZE_EVENT_TOPICS:
        return BronzeEnvelopeValidation(False, "unknown_event_type", event_type, event_id)
    if BRONZE_EVENT_TOPICS[event_type] != topic:
        return BronzeEnvelopeValidation(False, "topic_event_type_mismatch", event_type, event_id)
    if decoded.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        return BronzeEnvelopeValidation(False, "unsupported_schema_version", event_type, event_id)
    aggregate_type = decoded.get("aggregate_type")
    if not isinstance(aggregate_type, str) or not aggregate_type.strip():
        return BronzeEnvelopeValidation(False, "invalid_aggregate_type", event_type, event_id)

    aggregate_id = decoded.get("aggregate_id")
    correlation_id = decoded.get("correlation_id")
    causation_id = decoded.get("causation_id")
    if not _uuid_text(aggregate_id):
        return BronzeEnvelopeValidation(False, "invalid_aggregate_id", event_type, event_id)
    if not _uuid_text(correlation_id):
        return BronzeEnvelopeValidation(False, "invalid_correlation_id", event_type, event_id)
    if causation_id is not None and not _uuid_text(causation_id):
        return BronzeEnvelopeValidation(False, "invalid_causation_id", event_type, event_id)
    if key is None or key.decode("ascii", errors="ignore") != aggregate_id:
        return BronzeEnvelopeValidation(False, "kafka_key_mismatch", event_type, event_id)
    if not _aware_timestamp(decoded.get("occurred_at")):
        return BronzeEnvelopeValidation(False, "invalid_occurred_at", event_type, event_id)
    if not _aware_timestamp(decoded.get("recorded_at")):
        return BronzeEnvelopeValidation(False, "invalid_recorded_at", event_type, event_id)
    if not isinstance(decoded.get("payload"), dict):
        return BronzeEnvelopeValidation(False, "payload_not_object", event_type, event_id)

    return BronzeEnvelopeValidation(True, None, event_type, event_id)
