"""Run and verify Stage 7G controlled Spark / BigQuery-ready rebuild."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib import error, request
from uuid import uuid4

from confluent_kafka import Consumer, TopicPartition

from pharmstock.cdc import CDC_TOPICS, CONNECT_REST_URL, CONNECTOR_NAME
from pharmstock.rebuild import (
    BIGQUERY_REBUILD_DATASET,
    CDC_CHANGE_LOG_TABLE,
    CORE_ACCEPTANCE_MINIMUMS,
    POSTGRES_JDBC_PACKAGE,
    SNAPSHOT_TABLES,
    SPARK_KAFKA_PACKAGE,
    SPARK_VERSION,
    validate_offset_range,
    write_rebuild_contract,
)
from pharmstock.streaming.kafka import KafkaSettings

POSTGRES_COMPOSE = Path("infra/docker/docker-compose.postgres.yml")
KAFKA_COMPOSE = Path("infra/docker/docker-compose.kafka.yml")
CONNECT_COMPOSE = Path("infra/docker/docker-compose.stage7f.yml")
STAGE7G_COMPOSE = Path("infra/docker/docker-compose.stage7g.yml")
OUTPUT_DIR = Path("artifacts/stage7g")
STAGE7E_SUCCESS = Path("artifacts/stage7e/_SUCCESS")
STAGE7F_SUCCESS = Path("artifacts/stage7f/_SUCCESS")
SPARK_PACKAGES = f"{SPARK_KAFKA_PACKAGE},{POSTGRES_JDBC_PACKAGE}"


class Stage7GExecutionError(RuntimeError):
    """Raised when the Stage 7G rebuild contract cannot be satisfied."""


def _run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, capture_output=capture)


def _compose(*args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "docker",
            "compose",
            "-f",
            str(POSTGRES_COMPOSE),
            "-f",
            str(KAFKA_COMPOSE),
            "-f",
            str(CONNECT_COMPOSE),
            "-f",
            str(STAGE7G_COMPOSE),
            *args,
        ],
        capture=capture,
    )


def _connector_running() -> bool:
    try:
        with request.urlopen(
            f"{CONNECT_REST_URL}/connectors/{CONNECTOR_NAME}/status", timeout=10
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, error.URLError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    tasks = payload.get("tasks", [])
    return payload.get("connector", {}).get("state") == "RUNNING" and bool(tasks) and all(
        task.get("state") == "RUNNING" for task in tasks
    )


def _wait_for_connector(timeout_seconds: float = 90.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _connector_running():
            return
        time.sleep(2)
    raise Stage7GExecutionError(
        "Stage 7F Debezium connector is not RUNNING; rerun checkpoint 7f before Stage 7G"
    )


def _capture_high_watermarks(settings: KafkaSettings) -> dict[str, dict[str, int]]:
    consumer = Consumer(
        {
            "bootstrap.servers": settings.bootstrap_servers,
            "group.id": f"pharmstock-stage7g-offsets-{uuid4()}",
            "enable.auto.commit": False,
        }
    )
    offsets: dict[str, dict[str, int]] = {}
    try:
        for topic_spec in CDC_TOPICS:
            metadata = consumer.list_topics(topic_spec.topic, timeout=15)
            topic_metadata = metadata.topics.get(topic_spec.topic)
            if topic_metadata is None or topic_metadata.error is not None:
                raise Stage7GExecutionError(f"Kafka CDC topic unavailable: {topic_spec.topic}")
            partitions: dict[str, int] = {}
            for partition_id in sorted(topic_metadata.partitions):
                partition = TopicPartition(topic_spec.topic, partition_id)
                _low, high = consumer.get_watermark_offsets(
                    partition, timeout=10, cached=False
                )
                partitions[str(partition_id)] = int(high)
            offsets[topic_spec.topic] = partitions
    finally:
        consumer.close()
    return offsets


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _spark_submit(job: str) -> None:
    _compose(
        "run",
        "--rm",
        "spark-stage7g",
        "/opt/spark/bin/spark-submit",
        "--master",
        "local[2]",
        "--driver-memory",
        "2g",
        "--packages",
        SPARK_PACKAGES,
        "--conf",
        "spark.jars.ivy=/root/.ivy2",
        "--conf",
        "spark.driver.host=127.0.0.1",
        "--conf",
        "spark.default.parallelism=4",
        "--conf",
        "spark.sql.shuffle.partitions=4",
        f"/opt/pharmstock/spark/jobs/{job}",
    )


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise Stage7GExecutionError(f"expected JSON object: {path}")
    return payload


def _build_bigquery_plan(
    snapshot: dict[str, object], cdc: dict[str, object]
) -> dict[str, object]:
    snapshot_tables = snapshot.get("tables", {})
    if not isinstance(snapshot_tables, dict):
        raise Stage7GExecutionError("Stage 7G snapshot summary has invalid tables payload")
    reconciled = cdc.get("reconciled_tables", {})
    if not isinstance(reconciled, dict):
        reconciled = {}

    tables: list[dict[str, object]] = []
    for spec in SNAPSHOT_TABLES:
        summary = snapshot_tables.get(spec.source_table)
        if not isinstance(summary, dict):
            raise Stage7GExecutionError(f"missing snapshot summary table={spec.source_table}")
        reconciled_summary = reconciled.get(spec.source_table)
        if isinstance(reconciled_summary, dict):
            local_path = f"artifacts/stage7g/reconciled/{spec.schema_name}/{spec.table_name}"
            rows = int(reconciled_summary.get("rows", 0))
            source_layer = "reconciled_snapshot_plus_cdc"
        else:
            local_path = f"artifacts/stage7g/{spec.artifact_path}"
            rows = int(summary.get("rows", 0))
            source_layer = "historical_snapshot"
        tables.append(
            {
                "source_table": spec.source_table,
                "target_table": f"{BIGQUERY_REBUILD_DATASET}.{spec.bigquery_table}",
                "local_parquet_path": local_path,
                "rows": rows,
                "primary_key": list(spec.primary_key),
                "source_layer": source_layer,
                "write_strategy": "STAGING_THEN_ATOMIC_REPLACE",
            }
        )

    return {
        "stage": "7G",
        "generated_at": datetime.now(UTC).isoformat(),
        "cloud_mutation": False,
        "dataset": BIGQUERY_REBUILD_DATASET,
        "snapshot_tables": tables,
        "cdc_change_log": {
            "target_table": f"{BIGQUERY_REBUILD_DATASET}.{CDC_CHANGE_LOG_TABLE}",
            "local_parquet_path": "artifacts/stage7g/cdc_catchup",
            "rows": int(cdc.get("rows", 0)),
            "purpose": "auditable cutover delta; reconciled into changed snapshot tables",
        },
        "resume_offsets_file": "artifacts/stage7g/cdc_resume_offsets.json",
        "execution": "EXPLICIT_CLOUD_LOAD_ONLY_NOT_PERFORMED_BY_CHECKPOINT",
    }


def main() -> None:
    if shutil.which("docker") is None:
        raise SystemExit("Docker CLI is required for Stage 7G")
    if not STAGE7E_SUCCESS.is_file():
        raise SystemExit("Stage 7G requires Stage 7E PASS")
    if not STAGE7F_SUCCESS.is_file():
        raise SystemExit("Stage 7G requires Stage 7F PASS")

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)
    write_rebuild_contract(OUTPUT_DIR / "rebuild_contract.json")

    settings = KafkaSettings.from_env()
    print("=== PharmStock V2 / Stage 7G Large-scale Spark / BigQuery Rebuild ===")
    print(f"Spark version:                    {SPARK_VERSION}")
    print(f"Kafka connector:                  {SPARK_KAFKA_PACKAGE}")
    print(f"PostgreSQL JDBC:                  {POSTGRES_JDBC_PACKAGE}")
    print(f"Historical snapshot tables:       {len(SNAPSHOT_TABLES)}")
    print(f"CDC topics:                       {len(CDC_TOPICS)}")
    print("Historical replay through Kafka:  NO")
    print("Cutover gap protection:           YES")
    print("BigQuery-ready rebuild:           YES")
    print("Cloud mutation:                   NO")

    try:
        _compose("up", "-d", "postgres", "kafka", "connect")
        _wait_for_connector()

        print("\nCapturing CDC cutover start offsets...")
        start_offsets = _capture_high_watermarks(settings)
        _write_json(OUTPUT_DIR / "cutover_start_offsets.json", start_offsets)

        print("Running Spark historical snapshot from PostgreSQL...")
        _spark_submit("stage7g_snapshot.py")

        print("Capturing CDC cutover end offsets...")
        end_offsets = _capture_high_watermarks(settings)
        expected_catchup_rows = validate_offset_range(start_offsets, end_offsets)
        _write_json(OUTPUT_DIR / "cutover_end_offsets.json", end_offsets)
        _write_json(OUTPUT_DIR / "cdc_resume_offsets.json", end_offsets)

        print(
            "Running deterministic Kafka CDC catch-up "
            f"({expected_catchup_rows:,} records in cutover range)..."
        )
        _spark_submit("stage7g_cdc_catchup.py")

        snapshot = _read_json(OUTPUT_DIR / "snapshot_summary.json")
        cdc = _read_json(OUTPUT_DIR / "cdc_catchup_summary.json")
        if int(snapshot.get("table_count", 0)) != len(SNAPSHOT_TABLES):
            raise Stage7GExecutionError("not all Stage 7G snapshot tables were exported")
        if int(cdc.get("rows", -1)) != expected_catchup_rows:
            raise Stage7GExecutionError("CDC catch-up row count does not match cutover offsets")
        if int(cdc.get("invalid_rows", -1)) != 0:
            raise Stage7GExecutionError("CDC catch-up contains invalid rows")

        table_summaries = snapshot.get("tables", {})
        if not isinstance(table_summaries, dict):
            raise Stage7GExecutionError("invalid snapshot table summaries")
        minimum_checks: dict[str, dict[str, int | bool]] = {}
        for table, minimum in CORE_ACCEPTANCE_MINIMUMS.items():
            summary = table_summaries.get(table)
            actual = int(summary.get("rows", 0)) if isinstance(summary, dict) else 0
            minimum_checks[table] = {
                "minimum": minimum,
                "actual": actual,
                "passed": actual >= minimum,
            }
        failed_minimums = [
            table for table, check in minimum_checks.items() if not bool(check["passed"])
        ]
        if failed_minimums:
            raise Stage7GExecutionError(
                "historical rebuild minimums failed: " + ", ".join(failed_minimums)
            )

        bigquery_plan = _build_bigquery_plan(snapshot, cdc)
        _write_json(OUTPUT_DIR / "bigquery_rebuild_plan.json", bigquery_plan)
        verification = {
            "stage": "7G",
            "status": "PASS",
            "verified_at": datetime.now(UTC).isoformat(),
            "snapshot_table_count": int(snapshot["table_count"]),
            "snapshot_total_rows": int(snapshot["total_rows"]),
            "cdc_topic_count": len(CDC_TOPICS),
            "cutover_cdc_rows": expected_catchup_rows,
            "reconciled_table_count": len(cdc.get("reconciled_tables", {})),
            "minimum_checks": minimum_checks,
            "historical_replay_through_kafka": False,
            "cdc_resume_offsets_persisted": True,
            "bigquery_ready": True,
            "cloud_mutation": False,
        }
        _write_json(OUTPUT_DIR / "rebuild_verification.json", verification)
        _write_json(
            OUTPUT_DIR / "cutover_manifest.json",
            {
                "stage": "7G",
                "captured_at": datetime.now(UTC).isoformat(),
                "start_offsets": start_offsets,
                "end_offsets": end_offsets,
                "catchup_records": expected_catchup_rows,
                "resume_offsets": end_offsets,
            },
        )
        (OUTPUT_DIR / "_SUCCESS").write_text("PASS\n", encoding="utf-8")
    except (subprocess.CalledProcessError, Stage7GExecutionError, ValueError) as exc:
        raise SystemExit(f"Stage 7G failed: {exc}") from exc

    print("\nStage 7G verification:")
    print(f"  Historical snapshot tables:   {verification['snapshot_table_count']}")
    print(f"  Historical snapshot rows:     {verification['snapshot_total_rows']:,}")
    print(f"  CDC cutover records:          {verification['cutover_cdc_rows']:,}")
    print(f"  Reconciled changed tables:    {verification['reconciled_table_count']}")
    print("  Kafka historical replay:      NO")
    print("  CDC resume offsets:           SAVED")
    print("  BigQuery-ready Parquet:       YES")
    print("  Cloud mutation:               NO")
    print("\nGenerated files:")
    print(r"  artifacts\stage7g\rebuild_contract.json")
    print(r"  artifacts\stage7g\snapshot_summary.json")
    print(r"  artifacts\stage7g\cdc_catchup_summary.json")
    print(r"  artifacts\stage7g\cutover_manifest.json")
    print(r"  artifacts\stage7g\cdc_resume_offsets.json")
    print(r"  artifacts\stage7g\bigquery_rebuild_plan.json")
    print(r"  artifacts\stage7g\rebuild_verification.json")
    print("\nSTAGE_7G_STATUS=PASS")


if __name__ == "__main__":
    main()
