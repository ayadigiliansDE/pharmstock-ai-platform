"""Publish and consume a bounded cross-topic Stage 3B replay for local verification."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pharmstock.streaming as streaming

_STAGE2E_EVENTS = 300
_STAGE2F1_EVENTS = 200


def main() -> None:
    stage2e = Path("artifacts/stage2e")
    stage2f1 = Path("artifacts/stage2f1")
    output = Path("artifacts/stage3b")
    settings = streaming.KafkaSettings.from_env()
    admin = streaming.KafkaAdmin(settings)

    print("=== PharmStock V2 / Stage 3B Operational Stream Checkpoint ===")
    print(f"Bootstrap server:        {settings.bootstrap_servers}")
    print(f"Stage 2E sample events:  {_STAGE2E_EVENTS}")
    print(f"Stage 2F.1 sample events:{_STAGE2F1_EVENTS:>5}")
    print("Consumer topics:         SALES + INVENTORY + PROCUREMENT")
    print("Consumer offset mode:    LATEST / UNIQUE CHECKPOINT GROUP")
    print("DLQ expectation:         0 for validated simulator artifacts")
    print("Waiting for Kafka...")

    admin.wait_until_available()
    admin.ensure_topics()
    group_id = f"pharmstock-stage3b-checkpoint-{uuid4()}"
    topics = (
        streaming.SALES_TOPIC.name,
        streaming.INVENTORY_TOPIC.name,
        streaming.PROCUREMENT_TOPIC.name,
    )

    with streaming.KafkaEventConsumer(
        settings,
        group_id=group_id,
        topics=topics,
        auto_offset_reset="latest",
    ) as consumer:
        consumer.wait_for_assignment()
        result = streaming.replay_operational_events(
            producer=streaming.KafkaEventProducer(settings),
            dead_letter_producer=streaming.KafkaDeadLetterProducer(settings),
            stage2e_dir=stage2e,
            stage2f1_dir=stage2f1,
            output_dir=output,
            stage2e_event_limit=_STAGE2E_EVENTS,
            stage2f1_event_limit=_STAGE2F1_EVENTS,
            batch_size=250,
        )

        expected = set(result.published_event_ids)
        observed: set = set()
        consumed_by_topic: Counter[str] = Counter()
        consumed_by_type: Counter[str] = Counter()
        while len(observed) < len(expected):
            message = consumer.consume_one(timeout_seconds=30.0, commit=False)
            if message.event.event_id not in expected:
                continue
            if message.event.event_id in observed:
                raise RuntimeError(f"duplicate event observed: {message.event.event_id}")
            observed.add(message.event.event_id)
            consumed_by_topic[message.topic] += 1
            consumed_by_type[message.event.event_type] += 1
        consumer.commit()

    if observed != expected:
        missing = expected - observed
        raise RuntimeError(f"consumer verification missed {len(missing)} published events")
    if dict(sorted(consumed_by_topic.items())) != result.stats.topic_counts:
        raise RuntimeError("consumed topic counts do not match published topic counts")
    if dict(sorted(consumed_by_type.items())) != result.stats.event_type_counts:
        raise RuntimeError("consumed event-type counts do not match published counts")
    if result.stats.dead_letters != 0:
        raise RuntimeError("validated checkpoint unexpectedly produced dead letters")

    verification = {
        "stage": "3B",
        "verified_at": datetime.now(UTC).isoformat(),
        "consumer_group": group_id,
        "published_events": len(expected),
        "consumed_events": len(observed),
        "dead_letters": result.stats.dead_letters,
        "published_topic_counts": result.stats.topic_counts,
        "consumed_topic_counts": dict(sorted(consumed_by_topic.items())),
        "published_event_type_counts": result.stats.event_type_counts,
        "consumed_event_type_counts": dict(sorted(consumed_by_type.items())),
        "identity_check": "ALL_PUBLISHED_EVENT_IDS_CONSUMED_EXACTLY_ONCE_IN_CHECKPOINT_GROUP",
    }
    verification_path = output / "roundtrip_verification.json"
    verification_path.write_text(json.dumps(verification, indent=2), encoding="utf-8")
    (output / "_SUCCESS").write_text("STAGE_3B_VERIFIED\n", encoding="utf-8")

    print("\nCross-topic round trip:")
    print(f"  Published events:      {len(expected):,}")
    print(f"  Consumed events:       {len(observed):,}")
    print(f"  Dead letters:          {result.stats.dead_letters:,}")
    print("\nPublished / consumed by topic:")
    for topic, count in result.stats.topic_counts.items():
        print(f"  {topic:<34} {count:>6,} / {consumed_by_topic[topic]:>6,}")
    print("\nPublished / consumed by event type:")
    for event_type, count in result.stats.event_type_counts.items():
        print(f"  {event_type:<34} {count:>6,} / {consumed_by_type[event_type]:>6,}")
    print("\nGenerated files:")
    print(f"  {result.manifest_path.resolve()}")
    print(f"  {verification_path.resolve()}")
    print(f"  {(output / '_SUCCESS').resolve()}")
    print("\nSTAGE_3B_STATUS=PASS")


if __name__ == "__main__":
    main()
