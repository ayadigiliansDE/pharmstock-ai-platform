"""Stage 7J: Airflow + Data Quality + Monitoring for PharmStock V2."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from http.client import RemoteDisconnected
from pathlib import Path
from urllib import error, request

from pharmstock.observability.stage7j import (
    DEFAULT_HARD_STOP_GIB_7J,
    DEFAULT_WARN_GIB_7J,
    EXPECTED_CURRENT_VIEWS,
    EXPECTED_GOLD_MODELS,
    EXPECTED_RAW_ROWS,
    EXPECTED_RAW_TABLES,
    STAGE7J_ROOT,
    STAGE7J_SUCCESS,
    CheckResult,
    Stage7JReport,
    check_equal,
    check_storage,
    check_zero,
    render_dashboard,
    utc_now_iso,
    write_report,
)

AIRFLOW_COMPOSE = Path("infra/docker/docker-compose.stage7j.yml")
DEFAULT_RAW_DATASET = "pharmstock_ops_rebuild"
DEFAULT_DELTA_DATASET = "pharmstock_cdc_delta"
DEFAULT_CURRENT_DATASET = "pharmstock_ops_current"
DEFAULT_GOLD_DATASET = "pharmstock_rebuild_gold"
AIRFLOW_DAG_ID = "pharmstock_stage7j_health"
AIRFLOW_SCHEDULER_CONTAINER = "pharmacy-airflow-scheduler"
AIRFLOW_WEBSERVER_CONTAINER = "pharmacy-airflow-webserver"


def _bq_client(project_id: str):
    try:
        from google.cloud import bigquery
    except ImportError as exc:
        raise RuntimeError("Install project GCP extras before Stage 7J") from exc
    return bigquery.Client(project=project_id)


def _storage_bytes(client) -> int:
    total = 0
    for dataset in client.list_datasets():
        for item in client.list_tables(dataset.reference):
            table = client.get_table(item.reference)
            total += int(table.num_bytes or 0)
    return total


def _dataset_table_metadata(client, dataset_id: str) -> list[object]:
    try:
        return list(client.list_tables(dataset_id))
    except Exception:
        return []


def _raw_metrics(client, project_id: str, dataset_id: str) -> tuple[int, int]:
    tables = _dataset_table_metadata(client, dataset_id)
    row_count = 0
    for item in tables:
        table = client.get_table(item.reference)
        if getattr(table, "table_type", "TABLE") == "TABLE":
            row_count += int(table.num_rows or 0)
    return len(tables), row_count


def _typed_count(client, dataset_id: str, table_type: str) -> int:
    return sum(
        1
        for item in _dataset_table_metadata(client, dataset_id)
        if getattr(client.get_table(item.reference), "table_type", "") == table_type
    )


def _scalar_query(client, sql: str, location: str) -> int:
    rows = list(client.query(sql, location=location).result())
    if len(rows) != 1:
        raise RuntimeError("expected one aggregate row")
    return int(rows[0][0])


def _connector_check() -> CheckResult:
    base = os.getenv("CONNECT_REST_URL", "http://localhost:8083").rstrip("/")
    name = os.getenv("PHARMSTOCK_CONNECTOR_NAME", "pharmstock-postgres-cdc")
    try:
        with request.urlopen(f"{base}/connectors/{name}/status", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        connector = str(payload.get("connector", {}).get("state", "UNKNOWN"))
        task_states = [str(task.get("state", "UNKNOWN")) for task in payload.get("tasks", [])]
        healthy = (
            connector == "RUNNING"
            and bool(task_states)
            and all(x == "RUNNING" for x in task_states)
        )
        return CheckResult(
            name="debezium_connector_health",
            status="PASS" if healthy else "FAIL",
            observed=f"connector={connector}; tasks={task_states}",
            expected="connector=RUNNING; all tasks=RUNNING",
            severity="CRITICAL",
        )
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return CheckResult(
            name="debezium_connector_health",
            status="FAIL",
            observed=type(exc).__name__,
            expected="reachable RUNNING connector",
            severity="CRITICAL",
        )


def collect_report() -> Stage7JReport:
    project_id = os.getenv("PHARMSTOCK_BQ_PROJECT", "").strip()
    if not project_id:
        raise RuntimeError("PHARMSTOCK_BQ_PROJECT is required")
    location = os.getenv("PHARMSTOCK_BQ_LOCATION", "EU")
    raw = os.getenv("PHARMSTOCK_BQ_REBUILD_DATASET", DEFAULT_RAW_DATASET)
    delta = os.getenv("PHARMSTOCK_BQ_CDC_DATASET", DEFAULT_DELTA_DATASET)
    current = os.getenv("PHARMSTOCK_BQ_CURRENT_DATASET", DEFAULT_CURRENT_DATASET)
    gold = os.getenv("PHARMSTOCK_BQ_GOLD_DATASET", DEFAULT_GOLD_DATASET)
    warn = float(os.getenv("PHARMSTOCK_BQ_WARN_GIB", str(DEFAULT_WARN_GIB_7J)))
    hard_stop = float(
        os.getenv("PHARMSTOCK_BQ_HARD_STOP_GIB", str(DEFAULT_HARD_STOP_GIB_7J))
    )

    client = _bq_client(project_id)
    storage_gib = _storage_bytes(client) / (1024**3)
    raw_tables, raw_rows = _raw_metrics(client, project_id, raw)
    current_views = _typed_count(client, current, "VIEW")
    gold_tables = _typed_count(client, gold, "TABLE")

    bt = chr(96)
    events = f"{bt}{project_id}.{delta}.events{bt}"
    unique_events = _scalar_query(
        client, f"SELECT COUNT(DISTINCT event_id) FROM {events}", location
    )
    duplicate_rows = _scalar_query(
        client,
        f"SELECT COUNT(*) - COUNT(DISTINCT event_id) FROM {events}",
        location,
    )

    checks = (
        check_equal("raw_table_count", raw_tables, EXPECTED_RAW_TABLES),
        check_equal("raw_baseline_rows", raw_rows, EXPECTED_RAW_ROWS),
        check_equal("current_state_views", current_views, EXPECTED_CURRENT_VIEWS),
        check_equal("gold_model_count", gold_tables, EXPECTED_GOLD_MODELS),
        check_zero("duplicate_cdc_event_rows", duplicate_rows),
        CheckResult(
            name="cdc_event_store_readable",
            status="PASS" if unique_events >= 1 else "FAIL",
            observed=f"{unique_events:,} unique events",
            expected=">= 1 verified event",
        ),
        _connector_check(),
        check_storage(storage_gib, warn, hard_stop),
    )
    return Stage7JReport(
        generated_at=utc_now_iso(),
        project_id=project_id,
        storage_gib=storage_gib,
        checks=checks,
    )


def _print_report(report: Stage7JReport) -> None:
    print("\nStage 7J data-quality verification:")
    for check in report.checks:
        print(f"  {check.status:5} {check.name:30} observed={check.observed}")
    print(f"  BigQuery storage:              {report.storage_gib:.3f} GiB")
    print(f"STAGE_7J_DQ_STATUS={report.status}")


def _persist(report: Stage7JReport) -> None:
    write_report(report)
    STAGE7J_ROOT.mkdir(parents=True, exist_ok=True)
    (STAGE7J_ROOT / "monitoring_dashboard.html").write_text(
        render_dashboard(report), encoding="utf-8"
    )
    if report.status == "PASS":
        STAGE7J_SUCCESS.write_text(report.generated_at + "\n", encoding="utf-8")
    elif STAGE7J_SUCCESS.exists():
        STAGE7J_SUCCESS.unlink()


def _airflow_compose_up() -> None:
    base = ["docker", "compose", "-f", str(AIRFLOW_COMPOSE)]
    subprocess.run(base + ["up", "-d", "airflow-db"], check=True)
    subprocess.run(base + ["run", "--rm", "airflow-init"], check=True)
    subprocess.run(
        base
        + [
            "up",
            "-d",
            "--force-recreate",
            "airflow-webserver",
            "airflow-scheduler",
        ],
        check=True,
    )


def _airflow_cli(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = ["docker", "exec", AIRFLOW_SCHEDULER_CONTAINER, "airflow", *args]
    return subprocess.run(
        command,
        check=check,
        capture_output=True,
        text=True,
    )


def _json_output(result: subprocess.CompletedProcess[str]) -> object:
    payload = result.stdout.strip()
    if not payload:
        return []
    start = min(
        (index for index in (payload.find("["), payload.find("{")) if index >= 0),
        default=-1,
    )
    if start < 0:
        raise RuntimeError(f"Airflow CLI did not return JSON: {payload[-500:]}")
    return json.loads(payload[start:])


def _airflow_dag_ids() -> set[str]:
    result = _airflow_cli("dags", "list", "--output", "json")
    payload = _json_output(result)
    if not isinstance(payload, list):
        raise RuntimeError("Airflow DAG inventory must be a JSON list")
    return {str(item.get("dag_id")) for item in payload if isinstance(item, dict)}


def _airflow_import_errors() -> object:
    result = _airflow_cli(
        "dags", "list-import-errors", "--output", "json", check=False
    )
    try:
        return _json_output(result)
    except (json.JSONDecodeError, RuntimeError):
        return {"stdout": result.stdout[-2000:], "stderr": result.stderr[-2000:]}


def _wait_for_airflow_dag(timeout_seconds: int = 120) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_ids: set[str] = set()
    while time.monotonic() < deadline:
        try:
            last_ids = _airflow_dag_ids()
            if AIRFLOW_DAG_ID in last_ids:
                return
        except (subprocess.CalledProcessError, json.JSONDecodeError, RuntimeError):
            pass
        time.sleep(5)
    errors = _airflow_import_errors()
    raise RuntimeError(
        f"Airflow DAG {AIRFLOW_DAG_ID!r} not discovered; "
        f"visible={sorted(last_ids)}; import_errors={errors}"
    )


def _trigger_airflow_history_run(timeout_seconds: int = 300) -> str:
    run_id = f"manual__stage7j_history_{int(time.time())}"
    _airflow_cli("dags", "trigger", "--run-id", run_id, AIRFLOW_DAG_ID)
    deadline = time.monotonic() + timeout_seconds
    last_state = "queued"
    while time.monotonic() < deadline:
        result = _airflow_cli(
            "dags",
            "list-runs",
            "--dag-id",
            AIRFLOW_DAG_ID,
            "--output",
            "json",
        )
        payload = _json_output(result)
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict) or str(item.get("run_id")) != run_id:
                    continue
                last_state = str(item.get("state", "unknown")).lower()
                if last_state == "success":
                    return run_id
                if last_state == "failed":
                    raise RuntimeError(f"Airflow history run failed: {run_id}")
        time.sleep(5)
    raise RuntimeError(
        f"Airflow history run did not finish within {timeout_seconds}s: "
        f"run_id={run_id}; state={last_state}"
    )

def _wait_for_airflow(timeout_seconds: int = 300) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = "not started"
    while time.monotonic() < deadline:
        try:
            with request.urlopen("http://localhost:8088/health", timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            metadb = payload.get("metadatabase", {}).get("status")
            scheduler = payload.get("scheduler", {}).get("status")
            if metadb == "healthy" and scheduler == "healthy":
                return
            last_error = f"metadatabase={metadb}; scheduler={scheduler}"
        except (
            error.URLError,
            RemoteDisconnected,
            TimeoutError,
            ConnectionError,
            json.JSONDecodeError,
        ) as exc:
            last_error = type(exc).__name__
        time.sleep(5)
    raise RuntimeError(f"Airflow did not become healthy within {timeout_seconds}s: {last_error}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Stage 7J DQ and monitoring")
    parser.add_argument("--execute", action="store_true", help="persist reports and start Airflow")
    parser.add_argument("--no-airflow", action="store_true", help="skip Airflow startup")
    parser.add_argument("--airflow-task", action="store_true", help="run from the Airflow DAG")
    args = parser.parse_args()

    print("=== PharmStock V2 / Stage 7J Airflow + DQ + Monitoring ===")
    print(f"Project:            {os.getenv('PHARMSTOCK_BQ_PROJECT', '<unset>')}")
    print("Cloud writes:       NONE (monitoring reads only)")
    print("BigQuery raw copy:  NONE")
    print("Storage policy:     metadata + aggregate checks only")

    report = collect_report()
    _print_report(report)

    if args.execute or args.airflow_task:
        _persist(report)

    if args.execute and not args.no_airflow:
        _airflow_compose_up()
        _wait_for_airflow()
        _wait_for_airflow_dag()
        run_id = _trigger_airflow_history_run()
        print("Airflow control plane: HEALTHY")
        print(f"Airflow DAG discovered: {AIRFLOW_DAG_ID}")
        print(f"Airflow history run:    SUCCESS ({run_id})")
        print("Airflow schedule:       */15 * * * *")
        print("Airflow UI:             http://localhost:8088")

    if report.status != "PASS":
        raise SystemExit(2)

    if args.airflow_task:
        print("STAGE_7J_AIRFLOW_TASK_STATUS=PASS")
    elif args.execute:
        print("STAGE_7J_STATUS=PASS")
    else:
        print("STAGE_7J_DRY_RUN_STATUS=PASS")


if __name__ == "__main__":
    main()
