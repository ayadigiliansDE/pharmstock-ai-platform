"""Run the durable Stage 3C Kafka processor against live operational topics."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import pharmstock.streaming as streaming


def main() -> None:
    parser = argparse.ArgumentParser(description="Run durable PharmStock Kafka processing")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--group", default="pharmstock-stage3c-worker")
    parser.add_argument(
        "--state",
        type=Path,
        default=Path("artifacts/stage3c/processor_state.sqlite3"),
    )
    parser.add_argument("--offset-reset", choices=("earliest", "latest"), default="latest")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()
    if args.count <= 0:
        raise ValueError("--count must be positive")

    settings = streaming.KafkaSettings.from_env()
    topics = (
        streaming.SALES_TOPIC.name,
        streaming.INVENTORY_TOPIC.name,
        streaming.PROCUREMENT_TOPIC.name,
    )
    print("=== PharmStock V2 / Stage 3C Durable Processor ===")
    print(f"Group:                 {args.group}")
    print(f"Message count:         {args.count}")
    print(f"State store:           {args.state.resolve()}")
    print(f"Offset reset:          {args.offset_reset.upper()}")
    print("Commit rule:           AFTER PROCESSED / DUPLICATE / DLQ")
    print("Idempotency key:       event_id")
    print("Waiting for operational events...")

    counts: Counter[str] = Counter()
    with (
        streaming.KafkaEventConsumer(
            settings,
            group_id=args.group,
            topics=topics,
            auto_offset_reset=args.offset_reset,
        ) as consumer,
        streaming.DurableInboxStore(args.state) as store,
    ):
        consumer.wait_for_assignment()
        processor = streaming.DurableKafkaProcessor(
            consumer=consumer,
            store=store,
            dead_letter_producer=streaming.KafkaDeadLetterProducer(settings),
        )
        for index in range(1, args.count + 1):
            outcome = processor.process_one(timeout_seconds=args.timeout)
            counts[outcome.status.value] += 1
            print(
                f"  {index:>4}/{args.count} | {outcome.status.value:<9} | "
                f"{outcome.topic:<28} | p={outcome.partition} o={outcome.offset}"
            )
        ledger = store.counts()

    print("\nRun outcomes:")
    for status in streaming.ProcessingStatus:
        print(f"  {status.value:<10} {counts[status.value]:>8,}")
    print("\nDurable ledger:")
    print(f"  Processed event IDs:  {ledger.processed:,}")
    print(f"  Duplicate messages:   {ledger.duplicates:,}")
    print(f"  Failed messages:      {ledger.failures:,}")
    print(f"  DLQ published:        {ledger.dlq_published:,}")
    print("\nSTAGE_3C_PROCESSOR_STATUS=PASS")


if __name__ == "__main__":
    main()
