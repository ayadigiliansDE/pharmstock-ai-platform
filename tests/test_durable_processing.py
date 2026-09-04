import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pharmstock.domain import InventoryItem, ReorderPolicy, ReorderRequiredEvent
from pharmstock.streaming import (
    DeadLetterEnvelope,
    DurableInboxStore,
    DurableKafkaProcessor,
    FailureStage,
    IdempotencyConflictError,
    ProcessingStatus,
    RawConsumedKafkaMessage,
    deserialize_dead_letter,
    serialize_event,
)


def build_event(*, available: int = 4) -> ReorderRequiredEvent:
    item = InventoryItem(
        inventory_item_id=UUID("50000000-0000-0000-0000-000000000001"),
        branch_id=UUID("50000000-0000-0000-0000-000000000002"),
        product_id=UUID("50000000-0000-0000-0000-000000000003"),
        on_hand_quantity=available,
        reorder_policy=ReorderPolicy(reorder_point=5, target_stock_level=20),
    )
    return ReorderRequiredEvent.from_inventory(
        item,
        occurred_at=datetime(2026, 8, 22, tzinfo=UTC),
        correlation_id=UUID("50000000-0000-0000-0000-000000000004"),
    )


def raw_message(payload: bytes, *, offset: int) -> RawConsumedKafkaMessage:
    return RawConsumedKafkaMessage(
        topic="pharmstock.inventory.v1",
        partition=1,
        offset=offset,
        key=b"50000000-0000-0000-0000-000000000001",
        value=payload,
        headers=(("content-type", b"application/json"),),
    )


class FakeConsumer:
    def __init__(self) -> None:
        self.committed: list[tuple[str, int, int]] = []

    def commit_message(self, message: RawConsumedKafkaMessage) -> None:
        self.committed.append((message.topic, message.partition, message.offset))


class FakeDeadLetterProducer:
    def __init__(self) -> None:
        self.payloads: list[bytes] = []
        self.keys: list[bytes | None] = []

    def publish(
        self,
        payload: bytes,
        *,
        key: bytes | None = None,
        extra_headers: tuple[tuple[str, bytes], ...] = (),
        timeout_seconds: float = 10.0,
    ) -> None:
        del extra_headers, timeout_seconds
        self.payloads.append(payload)
        self.keys.append(key)


def build_processor(
    tmp_path: Path, *, handler=None
) -> tuple[DurableKafkaProcessor, DurableInboxStore, FakeConsumer, FakeDeadLetterProducer]:
    consumer = FakeConsumer()
    dlq = FakeDeadLetterProducer()
    store = DurableInboxStore(tmp_path / "processor.sqlite3")
    processor = DurableKafkaProcessor(
        consumer=consumer,  # type: ignore[arg-type]
        store=store,
        dead_letter_producer=dlq,  # type: ignore[arg-type]
        handler=handler,
    )
    return processor, store, consumer, dlq


def test_first_valid_event_is_durably_processed_and_committed(tmp_path: Path) -> None:
    event = build_event()
    processor, store, consumer, dlq = build_processor(tmp_path)

    outcome = processor.process_message(raw_message(serialize_event(event), offset=10))

    assert outcome.status is ProcessingStatus.PROCESSED
    assert outcome.event_id == event.event_id
    assert store.counts().processed == 1
    assert consumer.committed == [("pharmstock.inventory.v1", 1, 10)]
    assert dlq.payloads == []
    store.close()


def test_replay_of_same_event_id_is_recorded_as_duplicate_without_handler_rerun(
    tmp_path: Path,
) -> None:
    calls: list[UUID] = []
    event = build_event()
    processor, store, consumer, _dlq = build_processor(
        tmp_path, handler=lambda item: calls.append(item.event_id)
    )

    first = processor.process_message(raw_message(serialize_event(event), offset=20))
    second = processor.process_message(raw_message(serialize_event(event), offset=21))

    assert first.status is ProcessingStatus.PROCESSED
    assert second.status is ProcessingStatus.DUPLICATE
    assert calls == [event.event_id]
    assert store.counts().processed == 1
    assert store.counts().duplicates == 1
    assert len(consumer.committed) == 2
    store.close()


def test_invalid_json_is_persisted_to_failure_ledger_and_dlq(tmp_path: Path) -> None:
    processor, store, consumer, dlq = build_processor(tmp_path)

    outcome = processor.process_message(raw_message(b"not-json", offset=30))

    assert outcome.status is ProcessingStatus.FAILED
    assert outcome.failure_stage is FailureStage.DESERIALIZATION
    assert store.counts().failures == 1
    assert store.counts().dlq_published == 1
    assert len(dlq.payloads) == 1
    envelope = deserialize_dead_letter(dlq.payloads[0])
    assert envelope.failure_stage is FailureStage.DESERIALIZATION
    assert envelope.source_offset == 30
    assert consumer.committed[-1] == ("pharmstock.inventory.v1", 1, 30)
    store.close()


def test_handler_failure_is_sent_to_dlq_and_not_marked_processed(tmp_path: Path) -> None:
    event = build_event()

    def fail(_event) -> None:
        raise RuntimeError("sink unavailable")

    processor, store, _consumer, dlq = build_processor(tmp_path, handler=fail)
    outcome = processor.process_message(raw_message(serialize_event(event), offset=40))

    assert outcome.status is ProcessingStatus.FAILED
    assert outcome.failure_stage is FailureStage.PROCESSING
    assert store.counts().processed == 0
    assert store.counts().failures == 1
    envelope = deserialize_dead_letter(dlq.payloads[0])
    assert envelope.event_id == event.event_id
    assert envelope.error_message == "sink unavailable"
    store.close()


def test_same_event_id_with_different_validated_content_is_idempotency_failure(
    tmp_path: Path,
) -> None:
    event = build_event()
    processor, store, _consumer, dlq = build_processor(tmp_path)
    first = processor.process_message(raw_message(serialize_event(event), offset=50))
    assert first.status is ProcessingStatus.PROCESSED

    changed = event.model_copy(
        update={"occurred_at": datetime(2026, 8, 23, tzinfo=UTC)},
    )
    second = processor.process_message(raw_message(serialize_event(changed), offset=51))

    assert second.status is ProcessingStatus.FAILED
    assert second.failure_stage is FailureStage.IDEMPOTENCY
    envelope = deserialize_dead_letter(dlq.payloads[0])
    assert envelope.error_type == IdempotencyConflictError.__name__
    assert store.counts().processed == 1
    assert store.counts().duplicates == 0
    assert store.counts().failures == 1
    store.close()


def test_failure_source_location_is_not_republished_after_durable_dlq_mark(tmp_path: Path) -> None:
    processor, store, consumer, dlq = build_processor(tmp_path)
    source = raw_message(b"not-json", offset=60)

    first = processor.process_message(source)
    second = processor.process_message(source)

    assert first.status is ProcessingStatus.FAILED
    assert second.status is ProcessingStatus.FAILED
    assert len(dlq.payloads) == 1
    assert store.counts().failures == 1
    assert len(consumer.committed) == 2
    store.close()


def test_sqlite_inbox_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "durable.sqlite3"
    event = build_event()
    source = raw_message(serialize_event(event), offset=70)
    consumer = FakeConsumer()
    dlq = FakeDeadLetterProducer()

    with DurableInboxStore(path) as store:
        processor = DurableKafkaProcessor(
            consumer=consumer,  # type: ignore[arg-type]
            store=store,
            dead_letter_producer=dlq,  # type: ignore[arg-type]
        )
        assert processor.process_message(source).status is ProcessingStatus.PROCESSED

    with DurableInboxStore(path) as reopened:
        assert reopened.processed_event(event.event_id) is not None
        assert reopened.counts().processed == 1


def test_dead_letter_envelope_is_json_round_trip_safe() -> None:
    body = {
        "failure_id": "60000000-0000-0000-0000-000000000001",
        "failed_at": "2026-08-22T18:00:00+00:00",
        "failure_stage": "processing",
        "error_type": "RuntimeError",
        "error_message": "boom",
        "source_topic": "pharmstock.inventory.v1",
        "source_partition": 0,
        "source_offset": 5,
        "event_id": None,
        "event_type": None,
        "payload_sha256": "0" * 64,
        "key_base64": None,
        "payload_base64": "e30=",
        "headers": {},
    }
    envelope = DeadLetterEnvelope.model_validate_json(json.dumps(body))
    decoded = deserialize_dead_letter(envelope.model_dump_json().encode())
    assert decoded == envelope
