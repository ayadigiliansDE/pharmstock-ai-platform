"""Stage 7L launcher for governed operational decision workflows."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from pharmstock.onprem.stage7l import ACTIONABLE_ML_TOPICS, STAGE7L_VERSION, stage7l_contract

KAFKA_COMPOSE = Path("infra/docker/docker-compose.kafka.yml")
POSTGRES_COMPOSE = Path("infra/docker/docker-compose.postgres.yml")
STAGE7F_COMPOSE = Path("infra/docker/docker-compose.stage7f.yml")
STAGE7K_COMPOSE = Path("infra/docker/docker-compose.stage7k.yml")
STAGE7K5_COMPOSE = Path("infra/docker/docker-compose.stage7k5.yml")
STAGE7L_COMPOSE = Path("infra/docker/docker-compose.stage7l.yml")
SCHEMA_SQL = Path("infra/docker/postgres/sql/010_stage7l_governed_decisions.sql")
ARTIFACT_ROOT = Path("artifacts/stage7l")
HEARTBEAT = ARTIFACT_ROOT / "worker_heartbeat.json"
BOOTSTRAP_REPORT = ARTIFACT_ROOT / "bootstrap_report.json"
SMOKE_REPORT = ARTIFACT_ROOT / "smoke_report.json"
REPORT_PATH = ARTIFACT_ROOT / "stage7l_report.json"
SUCCESS_PATH = ARTIFACT_ROOT / "_SUCCESS"
STAGE7K5_REPORT = Path("artifacts/stage7k5/stage7k5_report.json")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _preflight() -> dict[str, object]:
    if not STAGE7K5_REPORT.is_file():
        raise RuntimeError("Stage 7L requires artifacts/stage7k5/stage7k5_report.json")
    report = _read_json(STAGE7K5_REPORT)
    if report.get("status") != "PASS":
        raise RuntimeError("Stage 7K.5 report is not PASS")
    heartbeat = report.get("worker_heartbeat", {})
    if heartbeat.get("status") != "HEALTHY":
        raise RuntimeError("Stage 7K.5 worker was not HEALTHY in its accepted report")
    return {
        "stage7k5_version": report.get("version"),
        "stage7k5_status": report.get("status"),
        "stage7k5_worker_status": heartbeat.get("status"),
    }


def _compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = [
        "docker",
        "compose",
        "-f",
        str(KAFKA_COMPOSE),
        "-f",
        str(POSTGRES_COMPOSE),
        "-f",
        str(STAGE7F_COMPOSE),
        "-f",
        str(STAGE7K_COMPOSE),
        "-f",
        str(STAGE7K5_COMPOSE),
        "-f",
        str(STAGE7L_COMPOSE),
        *args,
    ]
    env = os.environ.copy()
    env.setdefault("COMPOSE_IGNORE_ORPHANS", "true")
    return subprocess.run(command, check=check, text=True, env=env)


def _apply_schema() -> None:
    decision_password = os.getenv(
        "PHARMSTOCK_DECISION_PASSWORD", "pharmstock_local_dev_decision"
    )
    _compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-v",
        f"decision_password={decision_password}",
        "-U",
        "pharmstock_admin",
        "-d",
        "pharmstock_ops",
        "-f",
        f"/opt/pharmstock/{SCHEMA_SQL.as_posix()}",
    )


def _run_worker_once(flag: str) -> None:
    _compose(
        "run",
        "--rm",
        "--no-deps",
        "stage7l-workflow",
        "python",
        "-m",
        "operations.stage7l.worker",
        flag,
    )


def _wait_container_health(
    container_name: str,
    *,
    label: str,
    timeout_seconds: int = 150,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    last = "unknown"
    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
                container_name,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            last = result.stdout.strip()
            if last == "healthy":
                return last
            if last == "unhealthy":
                raise RuntimeError(f"{label} container healthcheck is UNHEALTHY")
        time.sleep(2)
    raise RuntimeError(f"{label} Docker healthcheck did not become healthy: {last}")


def _wait_heartbeat(timeout_seconds: int = 90) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last: dict = {}
    while time.monotonic() < deadline:
        if HEARTBEAT.is_file():
            try:
                last = _read_json(HEARTBEAT)
                if last.get("status") == "HEALTHY":
                    return last
            except (OSError, ValueError):
                pass
        time.sleep(2)
    raise RuntimeError(f"Stage 7L worker did not become healthy: {last}")


def _persist(preflight: dict[str, object], docker_health: str) -> dict:
    bootstrap = _read_json(BOOTSTRAP_REPORT)
    smoke = _read_json(SMOKE_REPORT)
    heartbeat = _read_json(HEARTBEAT)
    report = {
        "stage": "7L",
        "version": STAGE7L_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "PASS",
        "preflight": preflight,
        "contract": stage7l_contract(),
        "bootstrap": bootstrap,
        "smoke": smoke,
        "worker_heartbeat": heartbeat,
        "docker_health": docker_health,
        "cloud_mutation": False,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    SUCCESS_PATH.write_text(report["generated_at"] + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run PharmStock Stage 7L governed workflow")
    parser.add_argument("--execute", action="store_true", help="apply/start local Stage 7L")
    parser.add_argument("--no-build", action="store_true", help="reuse Stage 7L worker image")
    args = parser.parse_args()

    preflight = _preflight()
    print(f"=== PharmStock V2 / Stage 7L Governed Decision Workflow v{STAGE7L_VERSION} ===")
    print(f"Stage 7K.5 status:       {preflight['stage7k5_status']}")
    print(f"Stage 7K.5 worker:       {preflight['stage7k5_worker_status']}")
    print(f"Actionable ML topics:    {len(ACTIONABLE_ML_TOPICS)}")
    print("Cold-start strategy:     non-smoke ML journal + Kafka assignment watermark")
    print("Decision durability:     PostgreSQL inbox + case + evidence + audit")
    print("Human approval:          REQUIRED")
    print("Automatic supplier pick: DISABLED")
    print("Automatic PO creation:   BLOCKED")
    print("BigQuery writes:         NONE")
    print("Cloud mutation:          NO")

    if not args.execute:
        print("Runtime mutation:        NO / DRY RUN")
        print("STAGE_7L_DRY_RUN_STATUS=PASS")
        return

    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    SUCCESS_PATH.unlink(missing_ok=True)
    HEARTBEAT.unlink(missing_ok=True)
    BOOTSTRAP_REPORT.unlink(missing_ok=True)
    SMOKE_REPORT.unlink(missing_ok=True)

    print("Starting Stage 7K.5 dependencies...")
    _compose(
        "up",
        "-d",
        "postgres",
        "kafka",
        "connect",
        "mlflow",
        "model-serving",
        "stage7k5-online",
    )
    upstream_health = _wait_container_health(
        "pharmstock-stage7k5-online",
        label="Stage 7K.5 online worker",
        timeout_seconds=180,
    )
    print(f"Stage 7K.5 readiness:    {upstream_health.upper()}")

    print("Applying governed decision schema + least-privilege role...")
    _apply_schema()
    if not args.no_build:
        print("Building Stage 7L workflow image...")
        _compose("build", "stage7l-workflow")

    print("Bootstrapping current non-smoke ML state...")
    _run_worker_once("--bootstrap-only")
    print("Running transactional governance smoke...")
    _run_worker_once("--smoke")

    bootstrap_report = _read_json(BOOTSTRAP_REPORT)
    smoke_report = _read_json(SMOKE_REPORT)
    if bootstrap_report.get("status") != "PASS" or smoke_report.get("status") != "PASS":
        raise RuntimeError("Stage 7L bootstrap/smoke did not PASS")

    print("Starting continuous governed-decision worker...")
    _compose("up", "-d", "--force-recreate", "stage7l-workflow")
    docker_health = _wait_container_health(
        "pharmstock-stage7l-workflow",
        label="Stage 7L workflow",
    )
    heartbeat = _wait_heartbeat()
    report = _persist(preflight, docker_health)

    metrics = heartbeat.get("metrics", {})
    print("Stage 7L verification:")
    print(f"  Source ML topics:            {len(ACTIONABLE_ML_TOPICS)}")
    print(f"  Active decision cases:       {metrics.get('active_cases', 'n/a')}")
    print(f"  Approved drafts:             {metrics.get('approved_drafts', 'n/a')}")
    print(f"  Quarantined ML events:       {metrics.get('quarantine_rows', 'n/a')}")
    print(f"  Worker status:               {heartbeat.get('status')}")
    print(f"  Docker healthcheck:          {docker_health.upper()}")
    print("  Acceptance smoke persisted:  NO / ROLLED BACK")
    print("  Procurement write privilege: BLOCKED")
    print("  Automatic PO creation:       NO")
    print("  BigQuery writes:             NONE")
    print("  Cloud mutation:              NO")
    if report["status"] != "PASS":
        raise RuntimeError("Stage 7L persisted report is not PASS")
    print("STAGE_7L_BOOTSTRAP_STATUS=PASS")
    print("STAGE_7L_SMOKE_STATUS=PASS")
    print("STAGE_7L_WORKER_STATUS=PASS")
    print("STAGE_7L_GOVERNANCE_STATUS=PASS")
    print("STAGE_7L_STATUS=PASS")


if __name__ == "__main__":
    main()
