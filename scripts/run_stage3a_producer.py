"""Publish one visible PharmStock domain event to Kafka."""

from stage3a_common import build_sample_reorder_event

from pharmstock.streaming import KafkaAdmin, KafkaEventProducer, KafkaSettings, topic_for_event


def main() -> None:
    settings = KafkaSettings.from_env()
    admin = KafkaAdmin(settings)
    admin.wait_until_available()
    admin.ensure_topics()

    event = build_sample_reorder_event()
    topic = topic_for_event(event)
    published = KafkaEventProducer(settings).publish(event)

    print("=== PharmStock V2 / Stage 3A Producer ===")
    print(f"Event type:      {event.event_type}")
    print(f"Event ID:        {event.event_id}")
    print(f"Aggregate ID:    {event.aggregate_id}")
    print(f"Correlation ID:  {event.correlation_id}")
    print(f"Topic:           {topic.name}")
    print(f"Partition:       {published.partition}")
    print(f"Offset:          {published.offset}")
    print("\nSTAGE_3A_PRODUCER_STATUS=PASS")


if __name__ == "__main__":
    main()
