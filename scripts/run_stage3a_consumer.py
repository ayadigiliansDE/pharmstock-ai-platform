"""Consume validated PharmStock events from Kafka for manual learning."""

from __future__ import annotations

import argparse

from pharmstock.streaming import (
    INVENTORY_TOPIC,
    KafkaAdmin,
    KafkaEventConsumer,
    KafkaSettings,
    headers_to_dict,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Consume PharmStock Kafka events")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--group", default="pharmstock-stage3a-manual")
    args = parser.parse_args()
    if args.count <= 0:
        raise SystemExit("--count must be positive")

    settings = KafkaSettings.from_env()
    admin = KafkaAdmin(settings)
    admin.wait_until_available()
    admin.ensure_topics()

    print("=== PharmStock V2 / Stage 3A Consumer ===")
    print(f"Topic:      {INVENTORY_TOPIC.name}")
    print(f"Group:      {args.group}")
    print("Waiting for events...\n")

    with KafkaEventConsumer(
        settings,
        group_id=args.group,
        topics=(INVENTORY_TOPIC.name,),
        auto_offset_reset="latest",
    ) as consumer:
        consumer.wait_for_assignment()
        for index in range(1, args.count + 1):
            consumed = consumer.consume_one(timeout_seconds=args.timeout)
            event = consumed.event
            print(f"Message {index}/{args.count}")
            print(f"  event_type:     {event.event_type}")
            print(f"  event_id:       {event.event_id}")
            print(f"  correlation_id: {event.correlation_id}")
            print(f"  topic:          {consumed.topic}")
            print(f"  partition:      {consumed.partition}")
            print(f"  offset:         {consumed.offset}")
            print(f"  headers:        {headers_to_dict(consumed.headers)}")

    print("\nSTAGE_3A_CONSUMER_STATUS=PASS")


if __name__ == "__main__":
    main()
