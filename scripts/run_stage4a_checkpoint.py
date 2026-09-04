"""Stage 4A acceptance: Kafka -> Spark Bronze plus checkpoint restart verification."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path

from run_stage4a_spark import spark_compose_command

import pharmstock.streaming as streaming

_VALID_STAGE2E_EVENTS = 30
_VALID_STAGE2F1_EVENTS = 20


def _publish_malformed(settings: streaming.KafkaSettings) -> None:
    kafka = __import__("confluent_kafka")
    producer = kafka.Producer(
        {
            "bootstrap.servers": settings.bootstrap_servers,
            "client.id": f"{settings.client_id}-stage4a-malformed",
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
        key=b"stage4a-malformed",
        value=b'{"stage":"4a","malformed":',
        headers=[("content-type", b"application/json")],
        on_delivery=delivered,
    )
    remaining = producer.flush(10.0)
    if errors or remaining:
        raise RuntimeError(errors[0] if errors else "Stage 4A malformed probe was not delivered")


def _run_spark() -> dict[str, object]:
    completed = subprocess.run(spark_compose_command(), check=False)
    if completed.returncode:
        raise RuntimeError(f"Stage 4A Spark container exited with code {completed.returncode}")
    summary_path = Path("artifacts/stage4a/run_summary.json")
    if not summary_path.exists():
        raise RuntimeError("Spark completed without artifacts/stage4a/run_summary.json")
    return json.loads(summary_path.read_text(encoding="utf-8"))


def main() -> None:
    stage2e = Path("artifacts/stage2e")
    stage2f1 = Path("artifacts/stage2f1")
    output = Path("artifacts/stage4a")
    if not (stage2e / "_SUCCESS").exists() or not (stage2f1 / "_SUCCESS").exists():
        raise RuntimeError("Stage 4A requires completed Stage 2E and Stage 2F.1 artifacts")

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    settings = streaming.KafkaSettings.from_env()
    admin = streaming.KafkaAdmin(settings)
    print("=== PharmStock V2 / Stage 4A Spark Structured Streaming ===")
    print(f"Kafka bootstrap:          {settings.bootstrap_servers}")
    print("Spark runtime:            apache/spark:4.2.0-python3")
    print("Kafka connector:          spark-sql-kafka-0-10_2.13:4.2.0")
    print("Source topics:            SALES + INVENTORY + PROCUREMENT")
    print("Bronze format:            PARQUET / RAW PAYLOAD PRESERVED")
    print("Trigger:                  AVAILABLE NOW")
    print("Checkpoint test:          TWO PASSES / NO REPUBLISH BETWEEN PASSES")
    print("Waiting for Kafka...")
    admin.wait_until_available()
    admin.ensure_topics()

    events2e = tuple(islice(streaming.iter_stage2e_events(stage2e), _VALID_STAGE2E_EVENTS))
    events2f1 = tuple(islice(streaming.iter_stage2f1_events(stage2f1), _VALID_STAGE2F1_EVENTS))
    if len(events2e) != _VALID_STAGE2E_EVENTS or len(events2f1) != _VALID_STAGE2F1_EVENTS:
        raise RuntimeError("Stage 2E/2F.1 artifacts do not contain enough Stage 4A probe events")

    producer = streaming.KafkaEventProducer(settings)
    producer.publish_many((*events2e, *events2f1))
    _publish_malformed(settings)
    probe_count = _VALID_STAGE2E_EVENTS + _VALID_STAGE2F1_EVENTS
    print(f"Published Stage 4A probe: {probe_count} valid + 1 malformed")

    print("\n--- Spark pass 1: ingest available Kafka history ---")
    first = _run_spark()
    first_path = output / "first_pass_summary.json"
    first_path.write_text(json.dumps(first, indent=2, sort_keys=True), encoding="utf-8")

    print("\n--- Spark pass 2: same checkpoint, no new Kafka writes ---")
    second = _run_spark()
    second_path = output / "second_pass_summary.json"
    second_path.write_text(json.dumps(second, indent=2, sort_keys=True), encoding="utf-8")

    first_input = int(first["new_input_rows"])
    first_quarantine = int(first["new_quarantine_rows"])
    second_input = int(second["new_input_rows"])
    cumulative = int(second["cumulative_source_positions"])
    duplicates = int(second["duplicate_kafka_source_positions"])
    if first_input < _VALID_STAGE2E_EVENTS + _VALID_STAGE2F1_EVENTS + 1:
        raise RuntimeError("Spark first pass did not ingest the published Stage 4A probe")
    if first_quarantine < 1:
        raise RuntimeError("Spark quarantine did not capture the malformed Stage 4A probe")
    if second_input != 0:
        raise RuntimeError("Spark checkpoint restart reprocessed old Kafka offsets")
    if duplicates != 0:
        raise RuntimeError("Bronze contains duplicate topic/partition/offset identities")

    verification = {
        "stage": "4A",
        "verified_at": datetime.now(UTC).isoformat(),
        "first_pass_new_input_rows": first_input,
        "first_pass_new_bronze_rows": int(first["new_bronze_rows"]),
        "first_pass_new_quarantine_rows": first_quarantine,
        "second_pass_new_input_rows": second_input,
        "cumulative_source_positions": cumulative,
        "duplicate_kafka_source_positions": duplicates,
        "checkpoint_restart_verified": True,
        "malformed_quarantine_verified": True,
        "source_identity": ["topic", "partition", "offset"],
        "event_duplicates_policy": "PRESERVED_IN_BRONZE_DEDUPLICATE_LATER_IN_SILVER",
    }
    verification_path = output / "checkpoint_verification.json"
    verification_path.write_text(
        json.dumps(verification, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output / "_SUCCESS").write_text("STAGE_4A_VERIFIED\n", encoding="utf-8")

    print("\nStage 4A verification:")
    print(f"  First-pass input rows:     {first_input:,}")
    print(f"  First-pass Bronze rows:    {int(first['new_bronze_rows']):,}")
    print(f"  First-pass quarantine:     {first_quarantine:,}")
    print(f"  Restart new input rows:    {second_input:,}")
    print(f"  Cumulative source rows:    {cumulative:,}")
    print(f"  Duplicate Kafka positions: {duplicates:,}")
    print("\nGenerated files:")
    print(f"  {output.resolve() / 'bronze'}")
    print(f"  {output.resolve() / 'quarantine'}")
    print(f"  {output.resolve() / 'spark_checkpoint'}")
    print(f"  {verification_path.resolve()}")
    print("\nSTAGE_4A_STATUS=PASS")


if __name__ == "__main__":
    main()
