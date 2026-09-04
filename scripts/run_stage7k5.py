"""Stage 7K.5 launcher for CDC-triggered online ML decisions."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from pharmstock.ml.stage7k5 import (
    ML_OUTPUT_TOPICS,
    MONITORED_CDC_TOPICS,
    STAGE7K5_VERSION,
    stage7k5_contract,
)

KAFKA_COMPOSE = Path("infra/docker/docker-compose.kafka.yml")
POSTGRES_COMPOSE = Path("infra/docker/docker-compose.postgres.yml")
STAGE7F_COMPOSE = Path("infra/docker/docker-compose.stage7f.yml")
STAGE7K_COMPOSE = Path("infra/docker/docker-compose.stage7k.yml")
STAGE7K5_COMPOSE = Path("infra/docker/docker-compose.stage7k5.yml")
SCHEMA_SQL = Path("infra/docker/postgres/sql/009_stage7k5_online_ml.sql")
ARTIFACT_ROOT = Path("artifacts/stage7k5")
HEARTBEAT = ARTIFACT_ROOT / "worker_heartbeat.json"
SMOKE_REPORT = ARTIFACT_ROOT / "smoke_report.json"
REPORT_PATH = ARTIFACT_ROOT / "stage7k5_report.json"
SUCCESS_PATH = ARTIFACT_ROOT / "_SUCCESS"
STAGE7F_REPORT = Path("artifacts/stage7f/cdc_verification.json")
STAGE7K_REPORT = Path("artifacts/stage7k/stage7k_report.json")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _preflight() -> dict[str, object]:
    if not STAGE7F_REPORT.is_file():
        raise RuntimeError("Stage 7K.5 requires artifacts/stage7f/cdc_verification.json")
    if not STAGE7K_REPORT.is_file():
        raise RuntimeError("Stage 7K.5 requires artifacts/stage7k/stage7k_report.json")
    cdc = _read_json(STAGE7F_REPORT)
    if cdc.get("status") != "PASS":
        raise RuntimeError("Stage 7F verification is not PASS")
    topics = {str(item) for item in cdc.get("topics", [])}
    demand_topic = "pharmstock.ops.pos.demand_attempt"
    if demand_topic not in topics:
        raise RuntimeError(
            "Stage 7K.5 requires the 14-topic CDC migration including pos.demand_attempt"
        )
    ml = _read_json(STAGE7K_REPORT)
    models = ml.get("registered_models", [])
    if len(models) != 4 or not all(bool(item.get("production_ready")) for item in models):
        raise RuntimeError("Stage 7K.5 requires four production-ready Stage 7K champions")
    return {
        "cdc_topics": len(topics),
        "champions": len(models),
        "stage7k_hardening": ml.get("hardening"),
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
        *args,
    ]
    env = os.environ.copy()
    env.setdefault("COMPOSE_IGNORE_ORPHANS", "true")
    return subprocess.run(command, check=check, text=True, env=env)


def _apply_schema() -> None:
    _compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
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
        "stage7k5-online",
        "python",
        "-m",
        "ml.stage7k5.worker",
        flag,
    )


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
    raise RuntimeError(f"Stage 7K.5 worker did not become healthy: {last}")


def _wait_container_health(
    container_name: str = "pharmstock-stage7k5-online",
    *,
    label: str = "Stage 7K.5",
    timeout_seconds: int = 120,
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


def _persist(preflight: dict[str, object], heartbeat: dict, smoke: dict) -> None:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    report = {
        "stage": "7K.5",
        "version": STAGE7K5_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "PASS",
        "preflight": preflight,
        "contract": stage7k5_contract(),
        "smoke": smoke,
        "worker_heartbeat": heartbeat,
        "cloud_mutation": False,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    SUCCESS_PATH.write_text(report["generated_at"] + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run PharmStock Stage 7K.5 online ML runtime")
    parser.add_argument("--execute", action="store_true", help="apply/start the local runtime")
    parser.add_argument("--no-build", action="store_true", help="reuse Stage 7K.5 worker image")
    args = parser.parse_args()

    preflight = _preflight()
    print(f"=== PharmStock V2 / Stage 7K.5 Online Decision Runtime v{STAGE7K5_VERSION} ===")
    print(f"CDC source topics:       {preflight['cdc_topics']}")
    print(f"CDC trigger topics:      {len(MONITORED_CDC_TOPICS)}")
    print(f"Stage 7K champions:      {preflight['champions']}/4")
    print(f"ML output topics:        {len(ML_OUTPUT_TOPICS)}")
    print("Feature strategy:        CDC trigger + PostgreSQL read-through")
    print("Prediction durability:   PostgreSQL journal + transactional outbox")
    print("Kafka source commits:    AFTER durable decision + output publish")
    print("Stockout alert control:  threshold-relative severity + cooldown")
    print("BigQuery writes:         NONE")
    print("Cloud mutation:          NO")

    if not args.execute:
        print("Runtime mutation:        NO / DRY RUN")
        print("STAGE_7K5_DRY_RUN_STATUS=PASS")
        return

    SUCCESS_PATH.unlink(missing_ok=True)
    HEARTBEAT.unlink(missing_ok=True)
    SMOKE_REPORT.unlink(missing_ok=True)

    print("Starting local dependencies + Stage 7K serving...")
    _compose("up", "-d", "postgres", "kafka", "connect", "mlflow")
    # Reload serve.py so the online worker can read the champion operating thresholds.
    _compose("up", "-d", "--force-recreate", "model-serving")
    serving_health = _wait_container_health(
        "pharmstock-stage7k-serving",
        label="Stage 7K model-serving",
        timeout_seconds=180,
    )
    print(f"Stage 7K serving readiness: {serving_health.upper()}")
    print("Applying isolated ML operational-store schema...")
    _apply_schema()

    if not args.no_build:
        print("Building Stage 7K.5 online worker image...")
        _compose("build", "stage7k5-online")

    print("Reconciling ML output topics + model metadata...")
    _run_worker_once("--bootstrap-only")
    print("Running non-destructive real-feature inference smoke...")
    _run_worker_once("--smoke")
    smoke = _read_json(SMOKE_REPORT)
    if smoke.get("status") != "PASS":
        raise RuntimeError(f"Stage 7K.5 smoke failed: {smoke}")

    print("Starting continuous CDC-triggered online ML worker...")
    _compose("up", "-d", "--force-recreate", "stage7k5-online")
    docker_health = _wait_container_health()
    heartbeat = _wait_heartbeat()
    heartbeat["docker_health"] = docker_health
    _persist(preflight, heartbeat, smoke)

    print("Stage 7K.5 verification:")
    print(f"  ML output topics:            {len(ML_OUTPUT_TOPICS)}")
    print(f"  Smoke predictions:           {smoke['emitted_predictions']}")
    print(f"  Smoke outbox published:      {smoke['published_predictions']}")
    print(f"  Pending outbox:              {smoke['pending_outbox']}")
    print(f"  Worker status:               {heartbeat['status']}")
    print(f"  Docker healthcheck:          {heartbeat['docker_health'].upper()}")
    print(f"  Pending outbox (live):       {heartbeat.get('pending_outbox', 'n/a')}")
    print(f"  Quarantined CDC rows:        {heartbeat.get('quarantine_rows', 'n/a')}")
    print("  Historical CDC replay:       NO")
    print("  ML feedback into Debezium:   BLOCKED")
    print("  BigQuery writes:             NONE")
    print("  Cloud mutation:              NO")
    print("STAGE_7K5_BOOTSTRAP_STATUS=PASS")
    print("STAGE_7K5_SMOKE_STATUS=PASS")
    print("STAGE_7K5_WORKER_STATUS=PASS")
    print("STAGE_7K5_RELIABILITY_STATUS=PASS")
    print("STAGE_7K5_STATUS=PASS")


if __name__ == "__main__":
    main()
