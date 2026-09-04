"""Stable JSON serialization at the PharmStock Kafka boundary."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from pharmstock.domain import (
    DomainEvent,
    GoodsReceiptReceivedEvent,
    InventoryQuantityChangedEvent,
    PurchaseOrderCreatedEvent,
    ReorderRequiredEvent,
    RestockAppliedEvent,
    RestockReceivedEvent,
    SaleRecordedEvent,
    StockChangedEvent,
    UnitSaleFulfilledEvent,
)

KnownDomainEvent = (
    SaleRecordedEvent
    | RestockReceivedEvent
    | StockChangedEvent
    | ReorderRequiredEvent
    | UnitSaleFulfilledEvent
    | InventoryQuantityChangedEvent
    | PurchaseOrderCreatedEvent
    | GoodsReceiptReceivedEvent
    | RestockAppliedEvent
)

_EVENT_MODELS: dict[str, type[KnownDomainEvent]] = {
    "sale.recorded": SaleRecordedEvent,
    "restock.received": RestockReceivedEvent,
    "inventory.stock_changed": StockChangedEvent,
    "inventory.reorder_required": ReorderRequiredEvent,
    "sale.units_fulfilled": UnitSaleFulfilledEvent,
    "inventory.quantity_changed": InventoryQuantityChangedEvent,
    "purchase_order.created": PurchaseOrderCreatedEvent,
    "goods_receipt.received": GoodsReceiptReceivedEvent,
    "restock.applied": RestockAppliedEvent,
}


class EventDeserializationError(ValueError):
    """Raised when bytes from Kafka cannot be validated as a known event contract."""


def serialize_event(event: DomainEvent) -> bytes:
    return event.model_dump_json().encode("utf-8")


def event_key(event: DomainEvent) -> bytes:
    """Use aggregate identity as Kafka key so related records partition consistently."""

    return str(event.aggregate_id).encode("ascii")


def event_headers(event: DomainEvent) -> list[tuple[str, bytes]]:
    headers = [
        ("content-type", b"application/json"),
        ("event-type", event.event_type.encode("utf-8")),
        ("schema-version", event.schema_version.encode("ascii")),
        ("correlation-id", str(event.correlation_id).encode("ascii")),
        ("source", b"pharmstock-ai-platform"),
    ]
    if event.causation_id is not None:
        headers.append(("causation-id", str(event.causation_id).encode("ascii")))
    return headers


def deserialize_event(payload: bytes | bytearray | memoryview) -> KnownDomainEvent:
    try:
        decoded = json.loads(bytes(payload).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EventDeserializationError("Kafka payload is not valid UTF-8 JSON") from exc

    if not isinstance(decoded, dict):
        raise EventDeserializationError("Kafka event payload must be a JSON object")

    event_type = decoded.get("event_type")
    model = _EVENT_MODELS.get(event_type)
    if model is None:
        raise EventDeserializationError(f"unknown event_type={event_type!r}")

    try:
        return model.model_validate(decoded)
    except ValidationError as exc:
        raise EventDeserializationError(
            f"payload failed {event_type} schema validation"
        ) from exc


def headers_to_dict(headers: Iterable[tuple[str, bytes | None]] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in headers or ():
        result[key] = "" if value is None else value.decode("utf-8", errors="replace")
    return result


def uuid_from_ascii(value: bytes | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise EventDeserializationError("Kafka key is not a UUID") from exc


def json_safe(value: Any) -> Any:
    """Small helper for script output and future dead-letter metadata."""

    if isinstance(value, UUID):
        return str(value)
    return value
