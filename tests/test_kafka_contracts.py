from datetime import UTC, datetime
from uuid import UUID

import pytest

from pharmstock.domain import InventoryItem, ReorderPolicy, ReorderRequiredEvent
from pharmstock.streaming import (
    DEAD_LETTER_TOPIC,
    INVENTORY_TOPIC,
    MANAGED_TOPICS,
    PROCUREMENT_TOPIC,
    SALES_TOPIC,
    EventDeserializationError,
    KafkaSettings,
    deserialize_event,
    event_headers,
    event_key,
    headers_to_dict,
    serialize_event,
    topic_for_event,
    topic_for_event_type,
)


def build_event() -> ReorderRequiredEvent:
    item = InventoryItem(
        inventory_item_id=UUID("40000000-0000-0000-0000-000000000001"),
        branch_id=UUID("40000000-0000-0000-0000-000000000002"),
        product_id=UUID("40000000-0000-0000-0000-000000000003"),
        on_hand_quantity=4,
        reorder_policy=ReorderPolicy(reorder_point=5, target_stock_level=20),
    )
    return ReorderRequiredEvent.from_inventory(
        item,
        occurred_at=datetime(2026, 8, 22, tzinfo=UTC),
        correlation_id=UUID("40000000-0000-0000-0000-000000000004"),
    )


def test_managed_topic_names_are_unique_and_local_replication_is_one() -> None:
    assert len({topic.name for topic in MANAGED_TOPICS}) == len(MANAGED_TOPICS)
    assert all(topic.replication_factor == 1 for topic in MANAGED_TOPICS)
    assert SALES_TOPIC.partitions == 3
    assert INVENTORY_TOPIC.partitions == 3
    assert PROCUREMENT_TOPIC.partitions == 3
    assert DEAD_LETTER_TOPIC.partitions == 1


def test_event_type_routes_to_bounded_topic() -> None:
    assert topic_for_event_type("sale.recorded") is SALES_TOPIC
    assert topic_for_event_type("inventory.stock_changed") is INVENTORY_TOPIC
    assert topic_for_event_type("inventory.reorder_required") is INVENTORY_TOPIC
    assert topic_for_event_type("restock.received") is PROCUREMENT_TOPIC


def test_unknown_event_type_is_not_silently_routed() -> None:
    with pytest.raises(ValueError, match="no Kafka topic mapping"):
        topic_for_event_type("mystery.event")


def test_serialization_round_trip_preserves_validated_contract() -> None:
    event = build_event()
    decoded = deserialize_event(serialize_event(event))

    assert decoded == event
    assert decoded.event_id == event.event_id
    assert topic_for_event(decoded) is INVENTORY_TOPIC


def test_aggregate_id_is_the_partitioning_key() -> None:
    event = build_event()
    assert event_key(event) == str(event.aggregate_id).encode("ascii")


def test_kafka_headers_carry_contract_and_trace_context() -> None:
    event = build_event()
    headers = headers_to_dict(event_headers(event))

    assert headers["event-type"] == "inventory.reorder_required"
    assert headers["schema-version"] == "1.0"
    assert headers["correlation-id"] == str(event.correlation_id)
    assert headers["content-type"] == "application/json"


def test_invalid_json_is_rejected_at_consumer_boundary() -> None:
    with pytest.raises(EventDeserializationError, match="UTF-8 JSON"):
        deserialize_event(b"not-json")


def test_unknown_event_contract_is_rejected_at_consumer_boundary() -> None:
    with pytest.raises(EventDeserializationError, match="unknown event_type"):
        deserialize_event(b'{"event_type":"unknown.event"}')


def test_kafka_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka.example:19092")
    monkeypatch.setenv("KAFKA_CLIENT_ID", "pharmstock-test")

    settings = KafkaSettings.from_env()

    assert settings.bootstrap_servers == "kafka.example:19092"
    assert settings.client_id == "pharmstock-test"
