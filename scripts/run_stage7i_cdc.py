"""Run storage-guarded Stage 7I PostgreSQL CDC micro-batches into BigQuery.

BigQuery Sandbox does not provide streaming/DML. Stage 7I therefore keeps the
Stage 7H raw baseline immutable, appends only compact CDC events with load jobs,
and exposes current-state views that overlay the latest change per primary key.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error, request
from uuid import uuid4

from pharmstock.cdc import CDC_TOPICS, CONNECT_REST_URL, CONNECTOR_NAME, connector_config
from pharmstock.cdc.stage7i import (
    DEFAULT_WATCH_INTERVAL_SECONDS,
    SANDBOX_LIMIT_GIB,
    STAGE7H_SUCCESS,
    STAGE7I_RESUME_OFFSETS,
    STAGE7I_ROOT,
    Stage7IConfig,
    batch_id_for_offsets,
    capped_end_offsets,
    config_from_environment,
    current_state_view_sql,
    initial_resume_offsets,
    normalize_resume_offsets,
    passthrough_view_sql,
    projected_storage_gib,
    storage_guard_status,
    write_offsets_atomic,
)
from pharmstock.rebuild.contracts import (
    SNAPSHOT_TABLES,
    SPARK_KAFKA_PACKAGE,
    validate_offset_range,
)
from pharmstock.streaming.kafka import KafkaSettings

POSTGRES_COMPOSE = Path("infra/docker/docker-compose.postgres.yml")
KAFKA_COMPOSE = Path("infra/docker/docker-compose.kafka.yml")
CONNECT_COMPOSE = Path("infra/docker/docker-compose.stage7f.yml")
STAGE7I_COMPOSE = Path("infra/docker/docker-compose.stage7i.yml")
DEFAULT_LOCAL_CDC_PASSWORD = "pharmstock_local_dev_cdc"


class Stage7IExecutionError(RuntimeError):
    """Raised when Stage 7I cannot safely advance CDC offsets."""


def _parser() -> argparse.ArgumentParser:
    defaults = config_from_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="allow BigQuery mutation")
    parser.add_argument("--watch", action="store_true", help="keep polling for new CDC batches")
    parser.add_argument(
        "--probe",
        action="store_true",
        help="emit one temporary supplier c/u/d CDC probe before processing",
    )
    parser.add_argument("--interval", type=int, default=DEFAULT_WATCH_INTERVAL_SECONDS)
    parser.add_argument("--project", default=defaults.project_id)
    parser.add_argument("--raw-dataset", default=defaults.raw_dataset)
    parser.add_argument("--delta-dataset", default=defaults.delta_dataset)
    parser.add_argument("--current-dataset", default=defaults.current_dataset)
    parser.add_argument("--location", default=defaults.location)
    parser.add_argument("--max-records", type=int, default=defaults.max_batch_records)
    parser.add_argument("--warn-gib", type=float, default=defaults.warn_gib)
    parser.add_argument("--hard-stop-gib", type=float, default=defaults.hard_stop_gib)
    parser.add_argument(
        "--keep-local-batches",
        action="store_true",
        help="keep uploaded Parquet batch payloads instead of deleting them",
    )
    return parser


def _run(
    command: list[str],
    *,
    capture: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, capture_output=capture, env=env)


def _compose(*args: str, capture: bool = False, env: dict[str, str] | None = None):
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
            str(STAGE7I_COMPOSE),
            *args,
        ],
        capture=capture,
        env=env,
    )


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
        if exc.code == 404:
            return {"__http_status__": 404, "body": body}
        raise Stage7IExecutionError(f"Kafka Connect HTTP {exc.code}: {body}") from exc
    except (error.URLError, OSError) as exc:
        raise Stage7IExecutionError(f"Kafka Connect REST unavailable: {exc}") from exc
    return None if not raw else json.loads(raw.decode("utf-8"))


def _wait_for_connect(timeout_seconds: float = 120.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = _http_json("GET", "/connector-plugins")
            if isinstance(response, list):
                return
        except Stage7IExecutionError as exc:
            last_error = exc
        time.sleep(2)
    raise Stage7IExecutionError("Kafka Connect did not become ready") from last_error


def _ensure_connector(timeout_seconds: float = 120.0) -> None:
    _wait_for_connect()
    status = _http_json("GET", f"/connectors/{CONNECTOR_NAME}/status")
    password = os.getenv("PHARMSTOCK_CDC_PASSWORD", DEFAULT_LOCAL_CDC_PASSWORD).strip()
    config = connector_config(password)
    if isinstance(status, dict) and status.get("__http_status__") == 404:
        payload = {"name": CONNECTOR_NAME, "config": config}
        _http_json("POST", "/connectors", payload)
    else:
        # Reconcile table.include.list on every startup so late-created operational
        # tables (for example pos.demand_attempt) cannot silently stay outside CDC.
        _http_json("PUT", f"/connectors/{CONNECTOR_NAME}/config", config)

    deadline = time.monotonic() + timeout_seconds
    last_status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        status = _http_json("GET", f"/connectors/{CONNECTOR_NAME}/status")
        if isinstance(status, dict) and status.get("__http_status__") != 404:
            last_status = status
            connector_state = status.get("connector", {}).get("state")
            tasks = status.get("tasks", [])
            if connector_state == "RUNNING" and tasks and all(
                task.get("state") == "RUNNING" for task in tasks
            ):
                return
            if connector_state == "FAILED" or any(
                task.get("state") == "FAILED" for task in tasks
            ):
                raise Stage7IExecutionError(
                    "Debezium connector failed: " + json.dumps(status, ensure_ascii=False)
                )
        time.sleep(2)
    raise Stage7IExecutionError(
        "Debezium connector did not reach RUNNING: "
        + json.dumps(last_status, ensure_ascii=False)
    )


def _probe_change(sql: str) -> None:
    sql = " ".join(sql.split())
    shell = (
        'PGPASSWORD="$POSTGRES_PASSWORD" psql -v ON_ERROR_STOP=1 '
        '-U "$POSTGRES_USER" -d "$POSTGRES_DB" -c ' + json.dumps(sql)
    )
    _compose("exec", "-T", "postgres", "bash", "-lc", shell)


def _emit_cdc_probe() -> str:
    supplier_id = str(uuid4())
    probe_code = f"CDC7I-{supplier_id[:12]}"
    _probe_change(
        f"""
        INSERT INTO procurement.supplier (
            supplier_id, supplier_code, supplier_name, supplier_type, service_scope,
            reliability_score, nominal_lead_time_days, provenance_class, is_active
        ) VALUES (
            '{supplier_id}'::uuid, '{probe_code}', 'Stage 7I CDC Probe', 'CHECKPOINT',
            'CDC_BIGQUERY_ACCEPTANCE', 0.950000, 1, 'SYNTHETIC_CALIBRATED', true
        );
        """
    )
    _probe_change(
        f"""
        UPDATE procurement.supplier
        SET reliability_score = 0.987654, nominal_lead_time_days = 2
        WHERE supplier_id = '{supplier_id}'::uuid;
        """
    )
    _probe_change(
        f"DELETE FROM procurement.supplier WHERE supplier_id = '{supplier_id}'::uuid;"
    )
    print(f"CDC probe emitted:      {supplier_id} (c -> u -> d; row cleaned)")
    return supplier_id


def _capture_watermarks(
    settings: KafkaSettings,
) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, int]]]:
    from confluent_kafka import Consumer, TopicPartition

    consumer = Consumer(
        {
            "bootstrap.servers": settings.bootstrap_servers,
            "group.id": f"pharmstock-stage7i-watermark-{os.getpid()}",
            "enable.auto.commit": False,
        }
    )
    lows: dict[str, dict[str, int]] = {}
    highs: dict[str, dict[str, int]] = {}
    try:
        for item in CDC_TOPICS:
            metadata = consumer.list_topics(item.topic, timeout=10)
            topic_metadata = metadata.topics.get(item.topic)
            if topic_metadata is None or topic_metadata.error is not None:
                raise Stage7IExecutionError(f"Kafka topic unavailable: {item.topic}")
            low_parts: dict[str, int] = {}
            high_parts: dict[str, int] = {}
            for partition_id in sorted(topic_metadata.partitions):
                partition = TopicPartition(item.topic, partition_id)
                low, high = consumer.get_watermark_offsets(
                    partition, timeout=10, cached=False
                )
                low_parts[str(partition_id)] = int(low)
                high_parts[str(partition_id)] = int(high)
            lows[item.topic] = low_parts
            highs[item.topic] = high_parts
    finally:
        consumer.close()
    return lows, highs


def _assert_no_retention_gap(
    start: dict[str, dict[str, int]],
    low: dict[str, dict[str, int]],
    high: dict[str, dict[str, int]],
) -> None:
    validate_offset_range(start, high)
    for topic, partitions in start.items():
        if topic not in low or set(partitions) != set(low[topic]):
            raise Stage7IExecutionError(f"Kafka partition shape drift for {topic}")
        for partition, offset in partitions.items():
            low_offset = int(low[topic][partition])
            if int(offset) < low_offset:
                raise Stage7IExecutionError(
                    "Kafka retention gap detected: "
                    f"{topic}:{partition} resume={offset} low={low_offset}. "
                    "Offsets will NOT be advanced."
                )


def _spark_submit(batch_id: str, batch_root: Path) -> None:
    env = os.environ.copy()
    container_root = f"/opt/pharmstock/artifacts/stage7i/batches/{batch_id}"
    env.update(
        {
            "PHARMSTOCK_STAGE7I_BATCH_ID": batch_id,
            "SPARK_STAGE7I_BATCH_ROOT": container_root,
            "SPARK_STAGE7I_START_OFFSETS": f"{container_root}/start_offsets.json",
            "SPARK_STAGE7I_END_OFFSETS": f"{container_root}/end_offsets.json",
        }
    )
    _compose(
        "run",
        "--rm",
        "spark-stage7i",
        "/opt/spark/bin/spark-submit",
        "--master",
        "local[2]",
        "--driver-memory",
        "2g",
        "--packages",
        SPARK_KAFKA_PACKAGE,
        "--conf",
        "spark.jars.ivy=/root/.ivy2",
        "--conf",
        "spark.driver.host=127.0.0.1",
        "--conf",
        "spark.default.parallelism=4",
        "--conf",
        "spark.sql.shuffle.partitions=4",
        "/opt/pharmstock/spark/jobs/stage7i_cdc_microbatch.py",
        env=env,
    )
    if not (batch_root / "_SPARK_SUCCESS").is_file():
        raise Stage7IExecutionError("Spark micro-batch did not write _SPARK_SUCCESS")


def _project_storage_bytes(client: Any) -> int:
    total = 0
    for dataset in client.list_datasets():
        for table_item in client.list_tables(dataset.reference):
            if getattr(table_item, "table_type", "TABLE") != "TABLE":
                continue
            table = client.get_table(table_item.reference)
            total += int(table.num_bytes or 0)
    return total


def _ensure_dataset(client: Any, project: str, dataset_name: str, location: str) -> None:
    from google.cloud import bigquery

    dataset_id = f"{project}.{dataset_name}"
    dataset = bigquery.Dataset(dataset_id)
    dataset.location = location
    client.create_dataset(dataset, exists_ok=True)


def _ensure_events_table(client: Any, config: Stage7IConfig) -> str:
    from google.cloud import bigquery

    assert config.project_id is not None
    _ensure_dataset(client, config.project_id, config.delta_dataset, config.location)
    table_id = f"{config.project_id}.{config.delta_dataset}.events"

    # Spark-written Parquet is self-describing and commonly marks expression-derived
    # columns as nullable even after we have validated that required CDC fields are
    # populated. BigQuery compares the Parquet field mode with the destination table
    # mode on append. Keeping the physical delta table NULLABLE avoids a false
    # REQUIRED -> NULLABLE schema conflict; semantic requiredness is enforced by the
    # Spark validation gate before any cloud load.
    schema = [
        bigquery.SchemaField("event_id", "STRING"),
        bigquery.SchemaField("batch_id", "STRING"),
        bigquery.SchemaField("topic", "STRING"),
        bigquery.SchemaField("partition", "INTEGER"),
        bigquery.SchemaField("offset", "INTEGER"),
        bigquery.SchemaField("kafka_timestamp", "TIMESTAMP"),
        bigquery.SchemaField("key_json", "STRING"),
        bigquery.SchemaField("op", "STRING"),
        bigquery.SchemaField("source_schema", "STRING"),
        bigquery.SchemaField("source_table", "STRING"),
        bigquery.SchemaField("source_lsn", "INTEGER"),
        bigquery.SchemaField("source_tx_id", "INTEGER"),
        bigquery.SchemaField("source_ts_ms", "INTEGER"),
        bigquery.SchemaField("connector_ts_ms", "INTEGER"),
        bigquery.SchemaField("transaction_id", "STRING"),
        bigquery.SchemaField("before_json", "STRING"),
        bigquery.SchemaField("after_json", "STRING"),
        bigquery.SchemaField("ingested_at", "TIMESTAMP"),
    ]
    table = bigquery.Table(table_id, schema=schema)
    table.clustering_fields = ["source_schema", "source_table", "op", "batch_id"]
    client.create_table(table, exists_ok=True)

    actual = client.get_table(table_id)
    if actual.time_partitioning is not None:
        raise Stage7IExecutionError("Stage 7I delta table must remain UNPARTITIONED")

    # v0.30.0/v0.30.2 may already have created the empty events table with REQUIRED
    # fields before the first Parquet append failed. Relaxing REQUIRED -> NULLABLE is
    # metadata-only and does not copy/rewrite data, so it is safe for the storage guard.
    if any(field.mode == "REQUIRED" for field in actual.schema):
        actual.schema = schema
        actual = client.update_table(actual, ["schema"])
        print("Delta schema repair: REQUIRED -> NULLABLE (metadata only)", flush=True)

    if any(field.mode == "REQUIRED" for field in actual.schema):
        raise Stage7IExecutionError("Stage 7I delta schema relaxation did not persist")
    return table_id


def _create_current_views(client: Any, config: Stage7IConfig) -> int:
    assert config.project_id is not None
    _ensure_dataset(client, config.project_id, config.current_dataset, config.location)
    created = 0
    for spec in SNAPSHOT_TABLES:
        raw_id = (
            f"{config.project_id}.{config.raw_dataset}."
            f"{spec.schema_name}__{spec.table_name}"
        )
        raw = client.get_table(raw_id)
        if spec.cdc_managed:
            fields: list[tuple[str, str]] = []
            for field in raw.schema:
                if field.mode == "REPEATED" or field.field_type.upper() in {"RECORD", "STRUCT"}:
                    raise Stage7IExecutionError(
                        f"unsupported nested raw schema for {spec.source_table}: {field.name}"
                    )
                fields.append((field.name, field.field_type))
            sql = current_state_view_sql(
                project_id=config.project_id,
                raw_dataset=config.raw_dataset,
                delta_dataset=config.delta_dataset,
                current_dataset=config.current_dataset,
                source_table=spec.source_table,
                primary_key=spec.primary_key,
                fields=tuple(fields),
            )
        else:
            sql = passthrough_view_sql(
                project_id=config.project_id,
                raw_dataset=config.raw_dataset,
                current_dataset=config.current_dataset,
                source_table=spec.source_table,
            )
        client.query(sql, location=config.location).result()
        created += 1
    return created


def _load_batch(
    client: Any,
    config: Stage7IConfig,
    table_id: str,
    batch_id: str,
    parquet_files: tuple[Path, ...],
    expected_rows: int,
) -> dict[str, int]:
    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery

    loaded_files = 0
    reused_jobs = 0
    for index, path in enumerate(parquet_files, start=1):
        base_job_id = f"pharmstock_7i_{batch_id}_{index:04d}"
        job_id: str | None = None
        file_reused = False

        # BigQuery job IDs are immutable. A failed deterministic job from an earlier
        # attempt cannot be re-submitted with the same ID, so walk a deterministic
        # retry sequence. Successful prior jobs are reused, preserving idempotency.
        for retry_index in range(0, 20):
            candidate = (
                base_job_id
                if retry_index == 0
                else f"{base_job_id}_r{retry_index:02d}"
            )
            try:
                existing = client.get_job(candidate, location=config.location)
            except NotFound:
                job_id = candidate
                break

            try:
                existing.result()
            except Exception:  # noqa: BLE001 - failed immutable cloud job; try next ID
                continue

            reused_jobs += 1
            file_reused = True
            job_id = None
            print(
                f"    reuse load job file={index}/{len(parquet_files)} job={candidate}",
                flush=True,
            )
            break

        if file_reused:
            continue
        if job_id is None:
            raise Stage7IExecutionError(
                f"unable to allocate BigQuery load job id for file {index}"
            )

        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.PARQUET,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_RELAXATION],
        )
        with path.open("rb") as handle:
            job = client.load_table_from_file(
                handle,
                table_id,
                job_id=job_id,
                job_config=job_config,
                location=config.location,
                rewind=True,
            )
            job.result()
        loaded_files += 1
        print(
            f"    load file={index}/{len(parquet_files)} "
            f"size={path.stat().st_size / 1024**2:.1f} MiB job={job_id}",
            flush=True,
        )

    query = f"""
        SELECT COUNT(*) AS row_count, COUNT(DISTINCT event_id) AS unique_events
        FROM `{table_id}`
        WHERE batch_id = @batch_id
    """
    query_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id)]
    )
    result = client.query(query, job_config=query_config, location=config.location).result()
    row = next(iter(result))
    rows = int(row.row_count)
    unique_events = int(row.unique_events)
    if unique_events != expected_rows:
        raise Stage7IExecutionError(
            f"BigQuery batch verification failed expected={expected_rows} "
            f"unique_events={unique_events} rows={rows}"
        )
    return {
        "rows": rows,
        "unique_events": unique_events,
        "duplicate_rows": rows - unique_events,
        "loaded_files": loaded_files,
        "reused_jobs": reused_jobs,
    }


def _batch_parquet_files(batch_root: Path) -> tuple[Path, ...]:
    events = batch_root / "events"
    return tuple(sorted(path for path in events.rglob("*.parquet") if path.is_file()))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _config_from_args(args: argparse.Namespace) -> Stage7IConfig:
    config = Stage7IConfig(
        project_id=args.project,
        raw_dataset=args.raw_dataset,
        delta_dataset=args.delta_dataset,
        current_dataset=args.current_dataset,
        location=args.location,
        warn_gib=args.warn_gib,
        hard_stop_gib=args.hard_stop_gib,
        max_batch_records=args.max_records,
        parquet_expansion_factor=config_from_environment().parquet_expansion_factor,
    )
    config.validate()
    return config


def _run_one_cycle(
    *,
    config: Stage7IConfig,
    execute: bool,
    keep_local_batches: bool,
    cycle_number: int,
) -> str:
    from google.cloud import bigquery

    if not STAGE7H_SUCCESS.is_file():
        raise Stage7IExecutionError("Stage 7I requires Stage 7H PASS")
    source_path, persisted_start = initial_resume_offsets()
    settings = KafkaSettings.from_env()
    low, high = _capture_watermarks(settings)
    start, added_topics = normalize_resume_offsets(persisted_start, low, high)
    _assert_no_retention_gap(start, low, high)
    end = capped_end_offsets(start, high, config.max_batch_records)
    expected_rows = validate_offset_range(start, end)

    client = bigquery.Client(project=config.project_id)
    current_bytes = _project_storage_bytes(client)
    current_gib = current_bytes / (1024**3)
    if current_gib >= config.hard_stop_gib:
        raise Stage7IExecutionError(
            f"STORAGE_GUARD_STOP current={current_gib:.3f} GiB "
            f"hard_stop={config.hard_stop_gib:.3f} GiB"
        )

    print(f"\n--- Stage 7I cycle {cycle_number} ---")
    print(f"Resume source:       {source_path}")
    print(f"Current storage:     {current_gib:.3f} GiB / {SANDBOX_LIMIT_GIB:.1f} GiB")
    print(f"Storage warn:        {config.warn_gib:.3f} GiB")
    print(f"Storage hard stop:   {config.hard_stop_gib:.3f} GiB")
    print(f"Kafka pending batch: {expected_rows:,} records")
    if added_topics:
        print("Offset schema upgrade: " + ", ".join(added_topics))

    if not execute:
        print("Cloud mutation:      NO / DRY RUN")
        return "DRY_RUN"

    table_id = _ensure_events_table(client, config)
    view_count = _create_current_views(client, config)

    if expected_rows == 0:
        if added_topics or not STAGE7I_RESUME_OFFSETS.is_file():
            write_offsets_atomic(STAGE7I_RESUME_OFFSETS, start)
        print(f"Current-state views: {view_count}/26")
        print("CDC status:          IDLE / offsets already current")
        print("Cloud data mutation: NONE")
        return "IDLE"

    batch_id = batch_id_for_offsets(start, end)
    batch_root = STAGE7I_ROOT / "batches" / batch_id
    batch_root.mkdir(parents=True, exist_ok=True)
    _write_json(batch_root / "start_offsets.json", start)
    _write_json(batch_root / "end_offsets.json", end)

    print(f"Batch ID:            {batch_id}")
    print("Running Spark deterministic CDC micro-batch...")
    _spark_submit(batch_id, batch_root)
    parquet_files = _batch_parquet_files(batch_root)
    if not parquet_files:
        raise Stage7IExecutionError("Spark produced no Parquet files for a non-empty batch")
    parquet_bytes = sum(path.stat().st_size for path in parquet_files)
    projected_gib = projected_storage_gib(
        current_bytes,
        parquet_bytes,
        config.parquet_expansion_factor,
    )
    guard = storage_guard_status(current_gib, projected_gib, config)
    print(f"Local delta Parquet: {parquet_bytes / 1024**2:.1f} MiB")
    print(f"Projected storage:   {projected_gib:.3f} GiB (conservative)")
    print(f"Storage guard:       {guard}")
    if guard == "STOP":
        _write_json(
            batch_root / "storage_guard.json",
            {
                "status": "STOP",
                "current_gib": current_gib,
                "projected_gib": projected_gib,
                "warn_gib": config.warn_gib,
                "hard_stop_gib": config.hard_stop_gib,
                "offsets_advanced": False,
            },
        )
        raise Stage7IExecutionError(
            "Storage guard stopped before BigQuery load; local batch preserved and "
            "CDC offsets were NOT advanced"
        )

    report = _load_batch(
        client,
        config,
        table_id,
        batch_id,
        parquet_files,
        expected_rows,
    )
    post_bytes = _project_storage_bytes(client)
    post_gib = post_bytes / (1024**3)
    if post_gib >= config.hard_stop_gib:
        # The batch is already durably loaded. Commit offsets so the same events are
        # never intentionally reloaded, then stop future batches at the next cycle.
        print(
            "WARNING: storage reached the hard-stop boundary after a verified load; "
            "this batch will be committed but no next batch should run."
        )

    write_offsets_atomic(STAGE7I_RESUME_OFFSETS, end)
    load_report = {
        "stage": "7I",
        "status": "PASS",
        "batch_id": batch_id,
        "completed_at": datetime.now(UTC).isoformat(),
        "expected_rows": expected_rows,
        "bigquery_rows": report["rows"],
        "bigquery_unique_events": report["unique_events"],
        "duplicate_rows": report["duplicate_rows"],
        "loaded_files": report["loaded_files"],
        "reused_load_jobs": report["reused_jobs"],
        "storage_before_gib": current_gib,
        "storage_projected_gib": projected_gib,
        "storage_after_gib": post_gib,
        "storage_guard": guard,
        "hard_stop_gib": config.hard_stop_gib,
        "current_state_views": view_count,
        "offsets_advanced": True,
        "end_offsets": end,
        "historical_kafka_replay": False,
        "raw_baseline_rewritten": False,
    }
    _write_json(batch_root / "load_report.json", load_report)
    (batch_root / "_SUCCESS").write_text("PASS\n", encoding="utf-8")
    _write_json(STAGE7I_ROOT / "last_success.json", load_report)
    (STAGE7I_ROOT / "_SUCCESS").write_text("PASS\n", encoding="utf-8")

    if not keep_local_batches:
        shutil.rmtree(batch_root / "events", ignore_errors=True)

    print("\nStage 7I micro-batch verification:")
    print(f"  BigQuery unique events:   {report['unique_events']:,}")
    print(f"  Duplicate event rows:     {report['duplicate_rows']:,}")
    print(f"  Current-state views:      {view_count}/26")
    print(f"  Storage after:            {post_gib:.3f} GiB")
    print("  Raw baseline rewritten:   NO")
    print("  CDC resume offsets:       ADVANCED AFTER VERIFY")
    print("  Historical Kafka replay:  NO")
    print("STAGE_7I_BATCH_STATUS=PASS")
    return "PASS"


def main() -> None:
    args = _parser().parse_args()
    config = _config_from_args(args)
    if args.interval < 10:
        raise SystemExit("--interval must be >= 10 seconds")
    if shutil.which("docker") is None:
        raise SystemExit("Docker CLI is required for Stage 7I")

    STAGE7I_ROOT.mkdir(parents=True, exist_ok=True)
    print("=== PharmStock V2 / Stage 7I Continuous CDC -> Spark -> BigQuery ===")
    print(f"Project:                {config.project_id}")
    print(f"Raw baseline dataset:   {config.raw_dataset}")
    print(f"CDC delta dataset:      {config.delta_dataset}")
    print(f"Current-state dataset:  {config.current_dataset}")
    print(f"Location:               {config.location}")
    print("BigQuery mode:          SANDBOX SAFE / APPEND-ONLY LOAD JOBS")
    print("Raw baseline copy:      NONE")
    print("BigQuery DML/MERGE:     NONE")
    print("BigQuery streaming API: NONE")
    print(f"Max CDC batch:          {config.max_batch_records:,} events")
    print(
        f"Storage guard:          WARN {config.warn_gib:.1f} / "
        f"STOP {config.hard_stop_gib:.1f} GiB"
    )
    print(f"Cloud mutation:         {'YES' if args.execute else 'NO / DRY RUN'}")

    try:
        _compose("up", "-d", "postgres", "kafka", "connect")
        _ensure_connector()
        if args.probe:
            _emit_cdc_probe()
            time.sleep(2)
        cycle = 0
        while True:
            cycle += 1
            status = _run_one_cycle(
                config=config,
                execute=args.execute,
                keep_local_batches=args.keep_local_batches,
                cycle_number=cycle,
            )
            if not args.watch:
                break
            if status == "DRY_RUN":
                break
            time.sleep(args.interval)
    except (subprocess.CalledProcessError, Stage7IExecutionError, ValueError) as exc:
        raise SystemExit(f"Stage 7I stopped safely: {exc}") from exc

    if args.execute:
        print("\nSTAGE_7I_RUNTIME_STATUS=READY")
    else:
        print("\nSTAGE_7I_RUNTIME_STATUS=DRY_RUN_PASS")


if __name__ == "__main__":
    main()
