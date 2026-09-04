"""Silver-layer contracts for normalized, event-id-deduplicated operational facts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from pharmstock.analytics.silver_contracts import SILVER_TABLE_BY_EVENT
from pharmstock.streaming.serialization import EventDeserializationError, deserialize_event


@dataclass(frozen=True, slots=True)
class SilverEventValidation:
    is_valid: bool
    error: str | None
    event_id: str | None = None
    event_type: str | None = None
    silver_table: str | None = None


def semantic_event_hash(raw_json: str | bytes | bytearray | memoryview) -> str:
    """Hash immutable event semantics while ignoring replay-observation ``recorded_at``.

    ``event_id`` remains part of the hash. ``recorded_at`` is intentionally excluded because
    deterministic artifact replay may observe the same domain event at a different publication
    time. Business payload, occurrence time, causality, aggregate identity and schema remain
    protected against event-id reuse with different content.
    """

    if isinstance(raw_json, str):
        decoded = json.loads(raw_json)
    else:
        decoded = json.loads(bytes(raw_json).decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("Silver semantic hash requires a JSON object event")
    semantic = dict(decoded)
    semantic.pop("recorded_at", None)
    canonical = json.dumps(semantic, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_silver_event(raw_json: str | bytes | bytearray | memoryview) -> SilverEventValidation:
    """Validate one Bronze JSON event against its event-specific V1 domain contract."""

    payload = raw_json.encode("utf-8") if isinstance(raw_json, str) else bytes(raw_json)
    try:
        event = deserialize_event(payload)
    except EventDeserializationError as exc:
        return SilverEventValidation(False, str(exc))
    table = SILVER_TABLE_BY_EVENT.get(event.event_type)
    if table is None:
        return SilverEventValidation(
            False,
            "event type is not part of the Stage 4B Silver contract",
            str(event.event_id),
            event.event_type,
        )
    return SilverEventValidation(
        True,
        None,
        str(event.event_id),
        event.event_type,
        table,
    )


def silver_table_for_event_type(event_type: str) -> str:
    try:
        return SILVER_TABLE_BY_EVENT[event_type]
    except KeyError as exc:
        raise ValueError(f"unknown Stage 4B event_type={event_type!r}") from exc


def semantic_projection(decoded_event: dict[str, Any]) -> dict[str, Any]:
    """Return the JSON object used for semantic equality checks in tests/tooling."""

    result = dict(decoded_event)
    result.pop("recorded_at", None)
    return result
