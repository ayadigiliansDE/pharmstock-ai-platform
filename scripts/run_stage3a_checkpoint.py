"""End-to-end Kafka round-trip checkpoint for Stage 3A."""

from __future__ import annotations

from uuid import uuid4

from stage3a_common import build_sample_reorder_event

from pharmstock.streaming import (
    INVENTORY_TOPIC,
    KafkaAdmin,
    KafkaEventConsumer,
    KafkaEventProducer,
    KafkaSettings,
    event_key,
)


def main() -> None:
    settings = KafkaSettings.from_env()
    admin = KafkaAdmin(settings)

    print("=== PharmStock V2 / Stage 3A Kafka Foundation ===")
    print(f"Bootstrap server:  {settings.bootstrap_servers}")
    print("Broker mode:       LOCAL SINGLE-BROKER KRaft")
    print("Transport format:  VERSIONED JSON DOMAIN EVENTS")
    print("Producer safety:   IDEMPOTENCE + ACKS=ALL")
    print("Money / prices:    NOT INVOLVED")
    print("Waiting for Kafka...")

    admin.wait_until_available()
    topics = admin.ensure_topics()
    partitions = admin.topic_partitions()
    print("\nManaged topics:")
    for topic in topics:
        print(f"  {topic:<30} partitions={partitions[topic]}")

    group_id = f"pharmstock-stage3a-checkpoint-{uuid4()}"
    event = build_sample_reorder_event()

    with KafkaEventConsumer(
        settings,
        group_id=group_id,
        topics=(INVENTORY_TOPIC.name,),
        auto_offset_reset="latest",
    ) as consumer:
        consumer.wait_for_assignment()
        published = KafkaEventProducer(settings).publish(event)
        consumed = consumer.consume_one(timeout_seconds=30.0)

    if consumed.event.event_id != event.event_id:
        raise RuntimeError("Kafka round-trip returned a different event_id")
    if consumed.key != event_key(event):
        raise RuntimeError("Kafka round-trip changed the aggregate key")

    print("\nRound trip:")
    print(f"  event_type:      {event.event_type}")
    print(f"  event_id:        {event.event_id}")
    print(f"  topic:           {published.topic}")
    print(f"  partition:       {published.partition}")
    print(f"  produced_offset: {published.offset}")
    print(f"  consumed_offset: {consumed.offset}")
    print(f"  schema_version:  {consumed.event.schema_version}")
    print(f"  correlation_id:  {consumed.event.correlation_id}")
    print("\nSTAGE_3A_STATUS=PASS")


if __name__ == "__main__":
    main()
