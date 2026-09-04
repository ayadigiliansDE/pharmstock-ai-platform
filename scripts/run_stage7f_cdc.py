"""Deploy and verify Stage 7F PostgreSQL logical CDC through Debezium into Kafka."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib import error, request
from uuid import uuid4

from pharmstock.cdc import (
    CDC_TOPICS,
    CONNECT_REST_URL,
    CONNECTOR_NAME,
    DEBEZIUM_IMAGE,
    DEBEZIUM_RELEASE,
    SNAPSHOT_MODE,
    cdc_contract,
    connector_config,
    redacted_connector_config,
    topic_name,
)
from pharmstock.onprem import (
    CDC_PLUGIN,
    CDC_PUBLICATION,
    CDC_SLOT,
    CDC_TABLES,
    POSTGRES_DATABASE,
)
from pharmstock.streaming.kafka import KafkaAdmin, KafkaSettings
from pharmstock.streaming.topics import TopicSpec

POSTGRES_COMPOSE = Path("infra/docker/docker-compose.postgres.yml")
KAFKA_COMPOSE = Path("infra/docker/docker-compose.kafka.yml")
CONNECT_COMPOSE = Path("infra/docker/docker-compose.stage7f.yml")
OUTPUT_DIR = Path("artifacts/stage7f")
STAGE7E_SUCCESS = Path("artifacts/stage7e/_SUCCESS")
DEFAULT_LOCAL_CDC_PASSWORD = "pharmstock_local_dev_cdc"


class Stage7FExecutionError(RuntimeError):
    """Raised when the Stage 7F CDC acceptance contract cannot be satisfied."""


def _run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, capture_output=capture)


def _compose(*args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    command = [
        "docker",
        "compose",
        "-f",
        str(POSTGRES_COMPOSE),
        "-f",
        str(KAFKA_COMPOSE),
        "-f",
        str(CONNECT_COMPOSE),
        *args,
    ]
    return _run(command, capture=capture)


def _http_json(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    url = f"{CONNECT_REST_URL}{path}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=10) as response:
            raw = response.read()
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise Stage7FExecutionError(f"Kafka Connect HTTP {exc.code}: {body}") from exc
    except error.URLError as exc:
        raise Stage7FExecutionError(f"Kafka Connect REST unavailable: {exc.reason}") from exc
    except OSError as exc:
        # Docker Desktop may accept the TCP connection before Kafka Connect's
        # REST server is fully ready, then close it without an HTTP response.
        # Normalize those transient socket failures so readiness polling retries
        # instead of aborting Stage 7F with a raw traceback.
        raise Stage7FExecutionError(f"Kafka Connect REST unavailable: {exc}") from exc
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def _wait_for_connect(timeout_seconds: float = 120.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = _http_json("GET", "/connector-plugins")
            if isinstance(response, list):
                return
        except Stage7FExecutionError as exc:
            last_error = exc
        time.sleep(2)
    raise Stage7FExecutionError(
        "Kafka Connect did not become ready within 120 seconds"
    ) from last_error


def _wait_for_connector(timeout_seconds: float = 120.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            status = _http_json("GET", f"/connectors/{CONNECTOR_NAME}/status")
        except Stage7FExecutionError:
            time.sleep(2)
            continue
        if isinstance(status, dict):
            last_status = status
            connector_state = status.get("connector", {}).get("state")
            tasks = status.get("tasks", [])
            if connector_state == "RUNNING" and tasks and all(
                task.get("state") == "RUNNING" for task in tasks
            ):
                return status
            failed = [task for task in tasks if task.get("state") == "FAILED"]
            if connector_state == "FAILED" or failed:
                raise Stage7FExecutionError(
                    "Debezium connector failed: " + json.dumps(status, ensure_ascii=False)
                )
        time.sleep(2)
    raise Stage7FExecutionError(
        "Debezium connector did not reach RUNNING state: "
        + json.dumps(last_status, ensure_ascii=False)
    )


def _psql_scalar(sql: str) -> str:
    sql = " ".join(sql.split())
    shell = (
        'PGPASSWORD="$POSTGRES_PASSWORD" psql -v ON_ERROR_STOP=1 '
        '-U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc '
        + json.dumps(sql)
    )
    result = _compose("exec", "-T", "postgres", "bash", "-lc", shell, capture=True)
    return result.stdout.strip()


def _probe_change(sql: str) -> None:
    sql = " ".join(sql.split())
    shell = (
        'PGPASSWORD="$POSTGRES_PASSWORD" psql -v ON_ERROR_STOP=1 '
        '-U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '
        + json.dumps(sql)
    )
    _compose("exec", "-T", "postgres", "bash", "-lc", shell)


def _ensure_publication_tables() -> tuple[str, ...]:
    """Idempotently extend the existing publication with late-created CDC tables."""

    raw = _psql_scalar(
        "SELECT schemaname || '.' || tablename "
        "FROM pg_publication_tables "
        f"WHERE pubname = '{CDC_PUBLICATION}' ORDER BY 1;"
    )
    existing = {line.strip() for line in raw.splitlines() if line.strip()}
    missing = tuple(table for table in CDC_TABLES if table not in existing)
    for table in missing:
        _probe_change(f"ALTER PUBLICATION {CDC_PUBLICATION} ADD TABLE {table};")

    verified_raw = _psql_scalar(
        "SELECT schemaname || '.' || tablename "
        "FROM pg_publication_tables "
        f"WHERE pubname = '{CDC_PUBLICATION}' ORDER BY 1;"
    )
    verified = {line.strip() for line in verified_raw.splitlines() if line.strip()}
    still_missing = sorted(set(CDC_TABLES) - verified)
    if still_missing:
        raise Stage7FExecutionError(
            "CDC publication is missing canonical tables: " + ", ".join(still_missing)
        )
    return missing


def _ensure_cdc_topics(settings: KafkaSettings) -> tuple[str, ...]:
    specs = tuple(
        TopicSpec(
            name=item.topic,
            partitions=item.partitions,
            replication_factor=item.replication_factor,
            retention_ms=item.retention_ms,
        )
        for item in CDC_TOPICS
    )
    admin = KafkaAdmin(settings)
    admin.wait_until_available(timeout_seconds=90)
    return admin.ensure_topics(specs)


def _unwrap_connect_json(value: Any) -> dict[str, Any]:
    """Return the record payload for Kafka Connect JSON with or without schemas."""
    if not isinstance(value, dict):
        return {}
    wrapped = value.get("payload")
    if isinstance(wrapped, dict):
        return wrapped
    return value


def _consume_probe_events(
    settings: KafkaSettings,
    supplier_id: str,
    *,
    timeout_seconds: float = 90.0,
) -> list[dict[str, Any]]:
    from confluent_kafka import Consumer

    topic = topic_name("procurement.supplier")
    consumer = Consumer(
        {
            "bootstrap.servers": settings.bootstrap_servers,
            "group.id": f"pharmstock-stage7f-{uuid4()}",
            "auto.offset.reset": "latest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([topic])
    assignment_deadline = time.monotonic() + 20
    while time.monotonic() < assignment_deadline and not consumer.assignment():
        consumer.poll(0.25)
    assignment = consumer.assignment()
    if not assignment:
        consumer.close()
        raise Stage7FExecutionError("Stage 7F probe consumer did not receive assignment")

    # A group assignment alone does not guarantee that auto.offset.reset=latest has
    # already resolved a concrete starting offset. If the probe mutations are
    # written in that tiny window, Kafka may resolve "latest" *after* the events
    # arrive and the acceptance consumer will skip its own c/u/d events. Pin every
    # assigned partition to its current high watermark before touching PostgreSQL.
    from confluent_kafka import TopicPartition

    for partition in assignment:
        _low, high = consumer.get_watermark_offsets(partition, timeout=5.0, cached=False)
        consumer.seek(TopicPartition(partition.topic, partition.partition, high))

    probe_code = f"CDC7F-{supplier_id[:12]}"
    insert_sql = f"""
        INSERT INTO procurement.supplier (
            supplier_id, supplier_code, supplier_name, supplier_type, service_scope,
            reliability_score, nominal_lead_time_days, provenance_class, is_active
        ) VALUES (
            '{supplier_id}'::uuid, '{probe_code}', 'Stage 7F CDC Probe', 'CHECKPOINT',
            'CDC_ACCEPTANCE_ONLY', 0.950000, 1, 'SYNTHETIC_CALIBRATED', true
        );
    """
    update_sql = f"""
        UPDATE procurement.supplier
        SET reliability_score = 0.987654, nominal_lead_time_days = 2
        WHERE supplier_id = '{supplier_id}'::uuid;
    """
    delete_sql = f"DELETE FROM procurement.supplier WHERE supplier_id = '{supplier_id}'::uuid;"

    events: list[dict[str, Any]] = []
    try:
        _probe_change(insert_sql)
        _probe_change(update_sql)
        _probe_change(delete_sql)

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and len(events) < 3:
            message = consumer.poll(1.0)
            if message is None:
                continue
            if message.error():
                raise Stage7FExecutionError(str(message.error()))
            if message.value() is None:
                continue
            try:
                raw_value = json.loads(message.value().decode("utf-8"))
                raw_key = json.loads(message.key().decode("utf-8")) if message.key() else {}
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise Stage7FExecutionError("invalid JSON Debezium event") from exc

            # Kafka Connect's JSON converter emits {"schema": ..., "payload": ...}
            # when schemas are enabled. Accept both that canonical representation and
            # schemaless JSON so the checkpoint validates Debezium semantics rather
            # than a converter-specific envelope.
            payload = _unwrap_connect_json(raw_value)
            key = _unwrap_connect_json(raw_key)
            before = payload.get("before") or {}
            after = payload.get("after") or {}
            row_id = str(after.get("supplier_id") or before.get("supplier_id") or "")
            key_id = str(key.get("supplier_id") or "")
            if supplier_id not in (row_id, key_id):
                continue
            events.append(
                {
                    "op": payload.get("op"),
                    "topic": message.topic(),
                    "partition": message.partition(),
                    "offset": message.offset(),
                    "key": key,
                    "source": payload.get("source") or {},
                    "before": before,
                    "after": after,
                }
            )
    finally:
        consumer.close()
    return events


def _validate_events(events: list[dict[str, Any]], supplier_id: str) -> dict[str, bool]:
    ops = [event.get("op") for event in events]
    checks = {
        "three_probe_events_received": len(events) == 3,
        "insert_update_delete_order": ops == ["c", "u", "d"],
        "all_events_from_supplier_table": all(
            event.get("source", {}).get("schema") == "procurement"
            and event.get("source", {}).get("table") == "supplier"
            for event in events
        ),
        "all_events_have_probe_key": all(
            str(event.get("key", {}).get("supplier_id") or "") == supplier_id
            for event in events
        ),
        "delete_removed_probe_row": _psql_scalar(
            f"SELECT count(*) FROM procurement.supplier WHERE supplier_id = '{supplier_id}'::uuid;"
        )
        == "0",
    }
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise Stage7FExecutionError("Stage 7F CDC checks failed: " + ", ".join(failed))
    return checks


def main() -> None:
    if shutil.which("docker") is None:
        raise SystemExit("Docker CLI is required for Stage 7F")
    if not STAGE7E_SUCCESS.is_file():
        raise SystemExit("Stage 7F requires artifacts/stage7e/_SUCCESS; run checkpoint 7e first")

    cdc_password = os.getenv("PHARMSTOCK_CDC_PASSWORD", "").strip() or DEFAULT_LOCAL_CDC_PASSWORD
    settings = KafkaSettings.from_env()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    success_marker = OUTPUT_DIR / "_SUCCESS"
    if success_marker.exists():
        success_marker.unlink()

    print("=== PharmStock V2 / Stage 7F Debezium CDC -> Kafka ===")
    print(f"Debezium image:                 {DEBEZIUM_IMAGE}")
    print(f"Debezium compatible release:    {DEBEZIUM_RELEASE}")
    print(f"PostgreSQL database:             {POSTGRES_DATABASE}")
    print(f"Publication:                     {CDC_PUBLICATION}")
    print(f"Replication slot:                {CDC_SLOT}")
    print(f"Plugin:                          {CDC_PLUGIN}")
    print(f"Snapshot mode:                   {SNAPSHOT_MODE}")
    print("Historical Stage 7E replay:      NO (Stage 7G owns controlled rebuild)")
    print(f"CDC tables/topics:               {len(CDC_TOPICS)}")
    print("Cloud mutation:                  NO")

    try:
        _compose("up", "-d", "postgres", "kafka", "connect")
        _wait_for_connect()
        publication_additions = _ensure_publication_tables()
        topics = _ensure_cdc_topics(settings)

        config = connector_config(cdc_password)
        _http_json("PUT", f"/connectors/{CONNECTOR_NAME}/config", config)
        status = _wait_for_connector()

        slot_deadline = time.monotonic() + 30
        slot_state = ""
        while time.monotonic() < slot_deadline:
            slot_state = _psql_scalar(
                "SELECT plugin || '|' || active::text FROM pg_replication_slots "
                f"WHERE slot_name = '{CDC_SLOT}';"
            )
            if slot_state == f"{CDC_PLUGIN}|true":
                break
            time.sleep(1)
        if slot_state != f"{CDC_PLUGIN}|true":
            raise Stage7FExecutionError(f"unexpected replication slot state: {slot_state!r}")

        supplier_id = str(uuid4())
        events = _consume_probe_events(settings, supplier_id)
        checks = _validate_events(events, supplier_id)

        contract = cdc_contract()
        verification = {
            "status": "PASS",
            "connector": {
                "name": CONNECTOR_NAME,
                "state": status.get("connector", {}).get("state"),
                "tasks": status.get("tasks", []),
            },
            "replication_slot": {
                "name": CDC_SLOT,
                "plugin": CDC_PLUGIN,
                "active": True,
            },
            "publication": CDC_PUBLICATION,
            "publication_additions": list(publication_additions),
            "topics": list(topics),
            "probe": {
                "supplier_id": supplier_id,
                "operations": [event["op"] for event in events],
                "events": events,
            },
            "checks": checks,
            "cloud_mutation": False,
        }
        (OUTPUT_DIR / "cdc_contract.json").write_text(
            json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (OUTPUT_DIR / "connector_config_redacted.json").write_text(
            json.dumps(redacted_connector_config(cdc_password), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (OUTPUT_DIR / "cdc_verification.json").write_text(
            json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        success_marker.write_text("PASS\n", encoding="utf-8")
    except (subprocess.CalledProcessError, Stage7FExecutionError) as exc:
        raise SystemExit(f"Stage 7F failed: {exc}") from exc

    print("\nStage 7F verification:")
    print("  PostgreSQL logical CDC:        READY")
    print("  Debezium connector:            RUNNING")
    print(f"  Replication slot active:       {CDC_SLOT}")
    print(f"  Kafka CDC topics:              {len(CDC_TOPICS)}")
    print("  Live demand_attempt CDC:       ENABLED")
    print("  Probe INSERT/UPDATE/DELETE:    c -> u -> d")
    print("  Probe row cleaned up:          YES")
    print("  Historical 7E rows replayed:   NO")
    print("  Cloud mutation:                NO")
    print("\nGenerated files:")
    print(r"  artifacts\stage7f\cdc_contract.json")
    print(r"  artifacts\stage7f\connector_config_redacted.json")
    print(r"  artifacts\stage7f\cdc_verification.json")
    print("\nSTAGE_7F_STATUS=PASS")


if __name__ == "__main__":
    main()
