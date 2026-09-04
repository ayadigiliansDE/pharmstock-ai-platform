"""Verify durable processing, replay dedupe and DLQ handling against local Kafka."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from uuid import uuid4

import pharmstock.streaming as streaming

_UNIQUE_STAGE2E = 50
_UNIQUE_STAGE2F1 = 50


def _publish_invalid_inventory_payload(settings: streaming.KafkaSettings) -> None:
    kafka = __import__("confluent_kafka")
    producer = kafka.Producer(
        {
            "bootstrap.servers": settings.bootstrap_servers,
            "client.id": f"{settings.client_id}-stage3c-invalid-producer",
            "enable.idempotence": True,
            "acks": "all",
        }
    )
    errors: list[str] = []

    def delivered(error, _message) -> None:
        if error is not None:
            errors.append(str(error))

    producer.produce(
        streaming.INVENTORY_TOPIC.name,
        key=b"stage3c-invalid",
        value=b'{"event_type":"inventory.quantity_changed","broken":true}',
        headers=[("content-type", b"application/json")],
        on_delivery=delivered,
    )
    remaining = producer.flush(10.0)
    if errors or remaining:
        raise RuntimeError(errors[0] if errors else "invalid test message was not delivered")


def main() -> None:
    stage2e = Path("artifacts/stage2e")
    stage2f1 = Path("artifacts/stage2f1")
    output = Path("artifacts/stage3c")
    output.mkdir(parents=True, exist_ok=True)
    state_path = output / "checkpoint_state.sqlite3"
    state_path.unlink(missing_ok=True)
    Path(f"{state_path}-wal").unlink(missing_ok=True)
    Path(f"{state_path}-shm").unlink(missing_ok=True)
    (output / "_SUCCESS").unlink(missing_ok=True)

    settings = streaming.KafkaSettings.from_env()
    admin = streaming.KafkaAdmin(settings)
    print("=== PharmStock V2 / Stage 3C Durable Consumer Processing ===")
    print(f"Bootstrap server:        {settings.bootstrap_servers}")
    print(f"Unique Stage 2E events:  {_UNIQUE_STAGE2E}")
    print(f"Unique Stage 2F.1 events:{_UNIQUE_STAGE2F1:>5}")
    print("Replay copies:           1 duplicate copy / valid event")
    print("Forced processing fail:  1 validated event")
    print("Malformed validation:    1 raw Kafka message")
    print("State store:             SQLITE / WAL / FULL SYNC")
    print("Source commit:           AFTER durable outcome")
    print("Waiting for Kafka...")
    admin.wait_until_available()
    admin.ensure_topics()

    stage2e_events = tuple(islice(streaming.iter_stage2e_events(stage2e), _UNIQUE_STAGE2E))
    stage2f1_events = tuple(islice(streaming.iter_stage2f1_events(stage2f1), _UNIQUE_STAGE2F1 + 1))
    if len(stage2e_events) != _UNIQUE_STAGE2E or len(stage2f1_events) != _UNIQUE_STAGE2F1 + 1:
        raise RuntimeError("Stage 2E/2F.1 artifacts do not contain enough checkpoint events")
    unique_events = (*stage2e_events, *stage2f1_events[:_UNIQUE_STAGE2F1])
    forced_failure_event = stage2f1_events[-1]
    expected_unique_ids = {event.event_id for event in unique_events}
    if len(expected_unique_ids) != len(unique_events):
        raise RuntimeError("checkpoint source contains duplicate event IDs before replay")

    processor_group = f"pharmstock-stage3c-checkpoint-{uuid4()}"
    dlq_group = f"pharmstock-stage3c-dlq-checkpoint-{uuid4()}"
    business_topics = (
        streaming.SALES_TOPIC.name,
        streaming.INVENTORY_TOPIC.name,
        streaming.PROCUREMENT_TOPIC.name,
    )

    def handler(event: streaming.KnownDomainEvent) -> None:
        if event.event_id == forced_failure_event.event_id:
            raise RuntimeError("stage3c checkpoint forced processing failure")

    with (
        streaming.KafkaEventConsumer(
            settings,
            group_id=processor_group,
            topics=business_topics,
            auto_offset_reset="latest",
        ) as consumer,
        streaming.KafkaEventConsumer(
            settings,
            group_id=dlq_group,
            topics=(streaming.DEAD_LETTER_TOPIC.name,),
            auto_offset_reset="latest",
        ) as dlq_consumer,
        streaming.DurableInboxStore(state_path) as store,
    ):
        consumer.wait_for_assignment()
        dlq_consumer.wait_for_assignment()
        producer = streaming.KafkaEventProducer(settings)
        producer.publish_many(tuple(unique_events))
        producer.publish_many(tuple(unique_events))
        producer.publish(forced_failure_event)
        _publish_invalid_inventory_payload(settings)

        processor = streaming.DurableKafkaProcessor(
            consumer=consumer,
            store=store,
            dead_letter_producer=streaming.KafkaDeadLetterProducer(settings),
            handler=handler,
        )
        outcomes = []
        expected_source_messages = (2 * len(unique_events)) + 2
        for _ in range(expected_source_messages):
            outcomes.append(processor.process_one(timeout_seconds=30.0))

        dlq_envelopes = []
        for _ in range(2):
            raw = dlq_consumer.consume_raw_one(timeout_seconds=30.0, commit=True)
            dlq_envelopes.append(streaming.deserialize_dead_letter(raw.value))
        ledger = store.counts()

    outcome_counts = Counter(outcome.status.value for outcome in outcomes)
    expected_counts = {
        "processed": len(unique_events),
        "duplicate": len(unique_events),
        "failed": 2,
    }
    if dict(outcome_counts) != expected_counts:
        raise RuntimeError(
            f"durable processor outcomes mismatch: {dict(outcome_counts)} != {expected_counts}"
        )
    if ledger.processed != len(unique_events):
        raise RuntimeError("durable inbox did not retain exactly one row per valid event_id")
    if ledger.duplicates != len(unique_events):
        raise RuntimeError("duplicate-message ledger count mismatch")
    if ledger.failures != 2 or ledger.dlq_published != 2:
        raise RuntimeError("failure/DLQ ledger count mismatch")
    if {item.failure_stage for item in dlq_envelopes} != {
        streaming.FailureStage.DESERIALIZATION,
        streaming.FailureStage.PROCESSING,
    }:
        raise RuntimeError("DLQ did not contain both validation and processing failures")

    summary = {
        "stage": "3C",
        "verified_at": datetime.now(UTC).isoformat(),
        "processor_group": processor_group,
        "dlq_group": dlq_group,
        "unique_valid_event_ids": len(unique_events),
        "source_messages_consumed": len(outcomes),
        "outcomes": expected_counts,
        "ledger": {
            "processed": ledger.processed,
            "duplicates": ledger.duplicates,
            "failures": ledger.failures,
            "dlq_published": ledger.dlq_published,
        },
        "dlq_failure_stages": sorted(item.failure_stage.value for item in dlq_envelopes),
        "idempotency_contract": "EVENT_ID + CANONICAL_VALIDATED_PAYLOAD_HASH",
        "delivery_semantics": "KAFKA_AT_LEAST_ONCE_WITH_APPLICATION_INBOX_DEDUP",
    }
    summary_path = output / "processing_verification.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output / "_SUCCESS").write_text("STAGE_3C_VERIFIED\n", encoding="utf-8")

    print("\nDurable processing result:")
    print(f"  Source messages:       {len(outcomes):,}")
    print(f"  Processed:             {outcome_counts['processed']:,}")
    print(f"  Duplicates skipped:    {outcome_counts['duplicate']:,}")
    print(f"  Failed -> DLQ:         {outcome_counts['failed']:,}")
    print("\nDurable SQLite ledger:")
    print(f"  Unique processed IDs:  {ledger.processed:,}")
    print(f"  Duplicate messages:    {ledger.duplicates:,}")
    print(f"  Failure records:       {ledger.failures:,}")
    print(f"  DLQ published:         {ledger.dlq_published:,}")
    print("\nDLQ verification:")
    for envelope in sorted(dlq_envelopes, key=lambda item: item.failure_stage.value):
        print(
            f"  {envelope.failure_stage.value:<16} | {envelope.error_type:<28} | "
            f"{envelope.source_topic} p={envelope.source_partition} o={envelope.source_offset}"
        )
    print("\nGenerated files:")
    print(f"  {state_path.resolve()}")
    print(f"  {summary_path.resolve()}")
    print(f"  {(output / '_SUCCESS').resolve()}")
    print("\nSTAGE_3C_STATUS=PASS")


if __name__ == "__main__":
    main()
