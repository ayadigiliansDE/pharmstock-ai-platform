"""Inspect a bounded number of live PharmStock operational Kafka events."""

from __future__ import annotations

import argparse
from collections import Counter

import pharmstock.streaming as streaming


def main() -> None:
    parser = argparse.ArgumentParser(description="Consume visible Stage 3B operational events")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--group", default="pharmstock-stage3b-learning")
    args = parser.parse_args()
    if args.count <= 0:
        raise ValueError("--count must be positive")

    settings = streaming.KafkaSettings.from_env()
    topics = (
        streaming.SALES_TOPIC.name,
        streaming.INVENTORY_TOPIC.name,
        streaming.PROCUREMENT_TOPIC.name,
    )
    counts: Counter[str] = Counter()
    print("=== PharmStock V2 / Stage 3B Consumer ===")
    print(f"Group:  {args.group}")
    print(f"Count:  {args.count}")
    print("Waiting for operational events...")

    with streaming.KafkaEventConsumer(
        settings,
        group_id=args.group,
        topics=topics,
        auto_offset_reset="latest",
    ) as consumer:
        consumer.wait_for_assignment()
        for index in range(1, args.count + 1):
            message = consumer.consume_one(timeout_seconds=60.0, commit=False)
            counts[message.event.event_type] += 1
            print(
                f"  {index:>3}/{args.count} | {message.topic:<28} | "
                f"{message.event.event_type:<30} | p={message.partition} o={message.offset}"
            )
        consumer.commit()

    print("\nObserved event types:")
    for event_type, count in sorted(counts.items()):
        print(f"  {event_type:<34} {count:>6,}")
    print("\nSTAGE_3B_CONSUMER_STATUS=PASS")


if __name__ == "__main__":
    main()
