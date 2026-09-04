"""Replay completed operational simulator artifacts into Kafka topics."""

from __future__ import annotations

import argparse
from pathlib import Path

import pharmstock.streaming as streaming


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish Stage 2E/2F.1 simulator events to Kafka")
    parser.add_argument("--stage2e", type=Path, default=Path("artifacts/stage2e"))
    parser.add_argument("--stage2f1", type=Path, default=Path("artifacts/stage2f1"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/stage3b"))
    parser.add_argument("--stage2e-events", type=int)
    parser.add_argument("--stage2f1-events", type=int)
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

    settings = streaming.KafkaSettings.from_env()
    admin = streaming.KafkaAdmin(settings)
    print("=== PharmStock V2 / Stage 3B Simulator Event Streaming ===")
    print(f"Bootstrap server:        {settings.bootstrap_servers}")
    print(f"Stage 2E input:          {args.stage2e.resolve()}")
    print(f"Stage 2F.1 input:        {args.stage2f1.resolve()}")
    print("Bridge mode:             DETERMINISTIC ARTIFACT REPLAY")
    print("Event IDs:               UUID5 / REPLAY-STABLE")
    print("Money / prices:          NOT GENERATED")
    print(f"Kafka batch size:        {args.batch_size:,}")
    print("Waiting for Kafka...")
    admin.wait_until_available()
    admin.ensure_topics()

    result = streaming.replay_operational_events(
        producer=streaming.KafkaEventProducer(settings),
        dead_letter_producer=streaming.KafkaDeadLetterProducer(settings),
        stage2e_dir=args.stage2e,
        stage2f1_dir=args.stage2f1,
        output_dir=args.output,
        stage2e_event_limit=args.stage2e_events,
        stage2f1_event_limit=args.stage2f1_events,
        batch_size=args.batch_size,
    )

    print("\nPublished stream:")
    print(f"  Events published:      {result.stats.events_published:,}")
    print(f"  Dead letters:          {result.stats.dead_letters:,}")
    print("\nBy event type:")
    for event_type, count in result.stats.event_type_counts.items():
        print(f"  {event_type:<34} {count:>8,}")
    print("\nBy topic:")
    for topic, count in result.stats.topic_counts.items():
        print(f"  {topic:<34} {count:>8,}")
    print("\nGenerated files:")
    print(f"  {result.manifest_path.resolve()}")
    print(f"  {result.success_marker_path.resolve()}")
    print("\nSTAGE_3B_PUBLISH_STATUS=PASS")


if __name__ == "__main__":
    main()
