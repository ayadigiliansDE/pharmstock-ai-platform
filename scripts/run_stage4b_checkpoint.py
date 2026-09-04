"""Stage 4B acceptance: replay duplicates/conflicts, normalize Bronze, verify Silver."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from uuid import UUID, uuid5

from run_stage4a_spark import spark_compose_command as stage4a_spark_command
from run_stage4b_spark import spark_compose_command as stage4b_spark_command

import pharmstock.streaming as streaming

_DUPLICATE_STAGE2E = 10
_DUPLICATE_STAGE2F1 = 10
_PROBE_NAMESPACE = UUID("741a33d2-ec7d-4bf7-a933-8f077c38c36e")


def _run(command: list[str], label: str) -> None:
    completed = subprocess.run(command, check=False)
    if completed.returncode:
        raise RuntimeError(f"{label} exited with code {completed.returncode}")


def _publish_raw_invalid_payload(settings: streaming.KafkaSettings, source_event) -> None:
    kafka = __import__("confluent_kafka")
    decoded = json.loads(source_event.model_dump_json())
    decoded["event_id"] = str(uuid5(_PROBE_NAMESPACE, "stage4b-invalid-payload"))
    decoded["recorded_at"] = datetime.now(UTC).isoformat()
    decoded["payload"]["requested_quantity"] = 2
    decoded["payload"]["fulfilled_quantity"] = 5
    decoded["payload"]["lost_quantity"] = 0
    payload = json.dumps(decoded, separators=(",", ":")).encode("utf-8")
    producer = kafka.Producer(
        {
            "bootstrap.servers": settings.bootstrap_servers,
            "client.id": f"{settings.client_id}-stage4b-invalid",
            "enable.idempotence": True,
            "acks": "all",
        }
    )
    errors: list[str] = []

    def delivered(error, _message) -> None:
        if error is not None:
            errors.append(str(error))

    producer.produce(
        streaming.SALES_TOPIC.name,
        key=str(source_event.aggregate_id).encode("ascii"),
        value=payload,
        headers=[("content-type", b"application/json")],
        on_delivery=delivered,
    )
    remaining = producer.flush(10.0)
    if errors or remaining:
        message = errors[0] if errors else "invalid Stage 4B payload probe was not delivered"
        raise RuntimeError(message)


def _publish_conflict(producer: streaming.KafkaEventProducer, source_event) -> None:
    changed_payload = source_event.payload.model_copy(update={"channel": "stage4b_conflict"})
    conflict = source_event.model_copy(
        update={
            "payload": changed_payload,
            "recorded_at": datetime.now(UTC),
        }
    )
    producer.publish(conflict)


def _load_summary(path: Path) -> dict[str, object]:
    if not path.exists():
        raise RuntimeError(f"missing Spark summary: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    stage2e = Path("artifacts/stage2e")
    stage2f1 = Path("artifacts/stage2f1")
    stage4a = Path("artifacts/stage4a")
    stage4b = Path("artifacts/stage4b")
    if not (stage4a / "_SUCCESS").exists():
        raise RuntimeError(
            "Stage 4B requires a completed Stage 4A checkpoint on the current Kafka broker"
        )
    if not (stage2e / "_SUCCESS").exists() or not (stage2f1 / "_SUCCESS").exists():
        raise RuntimeError("Stage 4B requires Stage 2E and Stage 2F.1 artifacts")

    if stage4b.exists():
        shutil.rmtree(stage4b)

    settings = streaming.KafkaSettings.from_env()
    admin = streaming.KafkaAdmin(settings)
    print("=== PharmStock V2 / Stage 4B Silver Normalization ===")
    print(f"Kafka bootstrap:          {settings.bootstrap_servers}")
    print("Bronze source:            Stage 4A Parquet")
    print("Deduplication key:        event_id")
    print("Semantic hash:            EXCLUDES recorded_at ONLY")
    print("Conflict policy:          SAME event_id + DIFFERENT semantics -> REJECT ALL")
    print("Payload validation:       EVENT-SPECIFIC V1 BUSINESS CONTRACTS")
    print("Silver mode:              DETERMINISTIC FULL REFRESH")
    print("Waiting for Kafka...")
    admin.wait_until_available()
    admin.ensure_topics()

    events2e = tuple(islice(streaming.iter_stage2e_events(stage2e), _DUPLICATE_STAGE2E))
    events2f1 = tuple(islice(streaming.iter_stage2f1_events(stage2f1), _DUPLICATE_STAGE2F1))
    if len(events2e) != _DUPLICATE_STAGE2E or len(events2f1) != _DUPLICATE_STAGE2F1:
        raise RuntimeError("not enough operational events for Stage 4B probes")

    producer = streaming.KafkaEventProducer(settings)
    producer.publish_many((*events2e, *events2f1))

    coverage: dict[str, object] = {}
    for event in streaming.iter_operational_events(stage2e, stage2f1):
        coverage.setdefault(event.event_type, event)
        if len(coverage) == 6:
            break
    required_types = {
        "sale.units_fulfilled",
        "inventory.quantity_changed",
        "inventory.reorder_required",
        "purchase_order.created",
        "goods_receipt.received",
        "restock.applied",
    }
    if set(coverage) != required_types:
        raise RuntimeError("operational artifacts do not cover all Stage 4B event types")
    for event in coverage.values():
        producer.publish(event)

    sale_source = next(event for event in events2e if event.event_type == "sale.units_fulfilled")
    _publish_conflict(producer, sale_source)
    _publish_raw_invalid_payload(settings, sale_source)
    print(
        "Published Stage 4B probes: "
        f"{_DUPLICATE_STAGE2E + _DUPLICATE_STAGE2F1} replay copies + "
        "6 event-type coverage probes + 1 event-id conflict + 1 payload-invalid envelope"
    )

    print("\n--- Stage 4A incremental pass: append new Kafka positions to Bronze ---")
    _run(stage4a_spark_command(), "Stage 4A incremental Spark pass")
    bronze_summary = _load_summary(stage4a / "run_summary.json")
    if int(bronze_summary["new_input_rows"]) < 28:
        raise RuntimeError("Stage 4A did not ingest all Stage 4B probe messages")

    print("\n--- Stage 4B Silver pass 1 ---")
    _run(stage4b_spark_command(), "Stage 4B Spark pass 1")
    first = _load_summary(stage4b / "run_summary.json")
    first_copy = stage4b / "first_pass_summary.json"
    first_copy.write_text(json.dumps(first, indent=2, sort_keys=True), encoding="utf-8")

    print("\n--- Stage 4B Silver pass 2: no new Bronze rows ---")
    _run(stage4b_spark_command(), "Stage 4B Spark pass 2")
    second = _load_summary(stage4b / "run_summary.json")
    second_copy = stage4b / "second_pass_summary.json"
    second_copy.write_text(json.dumps(second, indent=2, sort_keys=True), encoding="utf-8")

    for field in (
        "bronze_rows",
        "silver_rows",
        "unique_silver_event_ids",
        "exact_duplicate_rows",
        "payload_reject_rows",
        "conflict_rows",
        "conflict_event_ids",
        "accounted_rows",
        "table_counts",
    ):
        if first[field] != second[field]:
            raise RuntimeError(f"Stage 4B full refresh is not deterministic for field={field}")

    if int(second["exact_duplicate_rows"]) < 19:
        raise RuntimeError("Stage 4B did not detect the replayed duplicate events")
    if int(second["payload_reject_rows"]) < 1:
        raise RuntimeError("Stage 4B did not reject the event-specific invalid payload")
    if int(second["conflict_event_ids"]) < 1 or int(second["conflict_rows"]) < 2:
        raise RuntimeError("Stage 4B did not quarantine the reused event_id conflict")
    if int(second["silver_rows"]) != int(second["unique_silver_event_ids"]):
        raise RuntimeError("Stage 4B Silver event IDs are not unique")
    if int(second["bronze_rows"]) != int(second["accounted_rows"]):
        raise RuntimeError("Stage 4B source accounting does not reconcile")

    table_counts = second["table_counts"]
    missing_tables = [name for name, count in table_counts.items() if int(count) <= 0]
    if missing_tables:
        raise RuntimeError(f"Stage 4B checkpoint did not populate Silver tables: {missing_tables}")

    verification = {
        "stage": "4B",
        "verified_at": datetime.now(UTC).isoformat(),
        "bronze_rows": int(second["bronze_rows"]),
        "silver_rows": int(second["silver_rows"]),
        "unique_silver_event_ids": int(second["unique_silver_event_ids"]),
        "exact_duplicate_rows": int(second["exact_duplicate_rows"]),
        "payload_reject_rows": int(second["payload_reject_rows"]),
        "conflict_rows": int(second["conflict_rows"]),
        "conflict_event_ids": int(second["conflict_event_ids"]),
        "table_counts": table_counts,
        "second_pass_same_counts": True,
        "deduplication_verified": True,
        "payload_validation_verified": True,
        "event_id_conflict_verified": True,
    }
    verification_path = stage4b / "silver_verification.json"
    verification_path.write_text(
        json.dumps(verification, indent=2, sort_keys=True), encoding="utf-8"
    )
    (stage4b / "_SUCCESS").write_text("STAGE_4B_VERIFIED\n", encoding="utf-8")

    print("\nStage 4B verification:")
    print(f"  Bronze rows:              {verification['bronze_rows']:,}")
    print(f"  Silver rows:              {verification['silver_rows']:,}")
    print(f"  Exact duplicates removed: {verification['exact_duplicate_rows']:,}")
    print(f"  Payload rejects:           {verification['payload_reject_rows']:,}")
    print(f"  Event-ID conflicts:        {verification['conflict_event_ids']:,}")
    print("  Silver tables:")
    for table_name, count in table_counts.items():
        print(f"    {table_name:<34} {int(count):>8,}")
    print("\nGenerated files:")
    print(f"  {(stage4b / 'silver').resolve()}")
    print(f"  {(stage4b / 'audit').resolve()}")
    print(f"  {verification_path.resolve()}")
    print("\nSTAGE_4B_STATUS=PASS")


if __name__ == "__main__":
    main()
