"""Stage 7M launcher for the operational decision API and workbench."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib import error, request

from pharmstock.onprem.stage7m import DEFAULT_PORT, STAGE7M_VERSION, stage7m_contract

KAFKA_COMPOSE = Path("infra/docker/docker-compose.kafka.yml")
POSTGRES_COMPOSE = Path("infra/docker/docker-compose.postgres.yml")
STAGE7F_COMPOSE = Path("infra/docker/docker-compose.stage7f.yml")
STAGE7K_COMPOSE = Path("infra/docker/docker-compose.stage7k.yml")
STAGE7K5_COMPOSE = Path("infra/docker/docker-compose.stage7k5.yml")
STAGE7L_COMPOSE = Path("infra/docker/docker-compose.stage7l.yml")
STAGE7M_COMPOSE = Path("infra/docker/docker-compose.stage7m.yml")
SCHEMA_SQL = Path("infra/docker/postgres/sql/011_stage7m_workbench_api.sql")
ARTIFACT_ROOT = Path("artifacts/stage7m")
REPORT_PATH = ARTIFACT_ROOT / "stage7m_report.json"
SMOKE_PATH = ARTIFACT_ROOT / "api_smoke_report.json"
SUCCESS_PATH = ARTIFACT_ROOT / "_SUCCESS"
STAGE7L_REPORT = Path("artifacts/stage7l/stage7l_report.json")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _preflight() -> dict[str, object]:
    if not STAGE7L_REPORT.is_file():
        raise RuntimeError("Stage 7M requires artifacts/stage7l/stage7l_report.json")
    report = _read_json(STAGE7L_REPORT)
    if report.get("status") != "PASS":
        raise RuntimeError("Stage 7L report is not PASS")
    heartbeat = report.get("worker_heartbeat", {})
    if heartbeat.get("status") != "HEALTHY":
        raise RuntimeError("Stage 7L worker was not HEALTHY in its accepted report")
    if report.get("smoke", {}).get("purchase_order_write_privilege") is not False:
        raise RuntimeError("Stage 7L accepted report did not prove blocked PO writes")
    return {
        "stage7l_version": report.get("version"),
        "stage7l_status": report.get("status"),
        "stage7l_worker_status": heartbeat.get("status"),
    }


def _compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = ["docker", "compose"]
    for path in (
        KAFKA_COMPOSE,
        POSTGRES_COMPOSE,
        STAGE7F_COMPOSE,
        STAGE7K_COMPOSE,
        STAGE7K5_COMPOSE,
        STAGE7L_COMPOSE,
        STAGE7M_COMPOSE,
    ):
        command.extend(("-f", str(path)))
    command.extend(args)
    env = os.environ.copy()
    env.setdefault("COMPOSE_IGNORE_ORPHANS", "true")
    return subprocess.run(command, check=check, text=True, env=env)


def _apply_schema() -> None:
    password = os.getenv("PHARMSTOCK_WORKBENCH_PASSWORD", "pharmstock_local_dev_workbench")
    _compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-v",
        f"workbench_password={password}",
        "-U",
        "pharmstock_admin",
        "-d",
        "pharmstock_ops",
        "-f",
        f"/opt/pharmstock/{SCHEMA_SQL.as_posix()}",
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


def _http_json(
    method: str,
    path: str,
    *,
    api_key: str | None = None,
    body: dict[str, object] | None = None,
    expected_status: int = 200,
) -> tuple[int, dict[str, object]]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-PharmStock-Api-Key"] = api_key
    req = request.Request(
        f"http://127.0.0.1:{DEFAULT_PORT}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with request.urlopen(req, timeout=10) as response:
            status_code = int(response.status)
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        status_code = int(exc.code)
        raw = exc.read().decode("utf-8")
        payload = json.loads(raw) if raw else {}
    if status_code != expected_status:
        raise RuntimeError(
            f"Stage 7M smoke expected HTTP {expected_status} for {path}, got {status_code}: "
            f"{payload}"
        )
    return status_code, payload


def _http_text(path: str, *, expected_status: int = 200) -> str:
    with request.urlopen(f"http://127.0.0.1:{DEFAULT_PORT}{path}", timeout=10) as response:
        if int(response.status) != expected_status:
            raise RuntimeError(f"Stage 7M expected HTTP {expected_status} for {path}")
        return response.read().decode("utf-8")


def _acceptance_smoke() -> dict[str, object]:
    viewer_key = os.getenv("PHARMSTOCK_STAGE7M_VIEWER_KEY", "stage7m-local-viewer")
    manager_key = os.getenv("PHARMSTOCK_STAGE7M_MANAGER_KEY", "stage7m-local-manager")

    _, health = _http_json("GET", "/health")
    _http_json("GET", "/v1/cases", expected_status=401)
    _, summary = _http_json("GET", "/v1/metrics/summary", api_key=viewer_key)
    _, cases = _http_json("GET", "/v1/cases?limit=10", api_key=manager_key)
    _http_json(
        "POST",
        "/v1/cases/00000000-0000-0000-0000-000000000000/actions",
        api_key=viewer_key,
        body={"action": "acknowledge", "note": "rbac acceptance smoke"},
        expected_status=403,
    )
    _, openapi = _http_json("GET", "/openapi.json")
    path_specs = openapi.get("paths", {})

    mutating_methods = {"post", "put", "patch", "delete"}
    allowed_mutation_routes = {
        ("/v1/cases/{case_id}/actions", "post"),
    }

    forbidden_paths = sorted(
        f"{method.upper()} {path}"
        for path, spec in path_specs.items()
        if isinstance(spec, dict)
        for method in spec
        if method.lower() in mutating_methods
        and (path, method.lower()) not in allowed_mutation_routes
    )

    if forbidden_paths:
        raise RuntimeError(
            "Stage 7M exposes unexpected mutation routes: "
            f"{forbidden_paths}"
        )
    workbench = _http_text("/workbench")
    if "PharmStock Operational Decision Workbench" not in workbench:
        raise RuntimeError("Stage 7M workbench did not render expected content")
    if health.get("procurement_write_blocked") is not True:
        raise RuntimeError("Stage 7M health did not prove procurement write block")
    if health.get("automatic_po_creation") is not False:
        raise RuntimeError("Stage 7M health reported automatic PO creation")

    report = {
        "status": "PASS",
        "health": health,
        "summary": summary,
        "case_count_sample": cases.get("count"),
        "unauthenticated_read_blocked": True,
        "viewer_mutation_blocked": True,
        "forbidden_execution_paths": forbidden_paths,
        "workbench_rendered": True,
        "cloud_mutation": False,
    }
    SMOKE_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def _persist(preflight: dict[str, object], docker_health: str, smoke: dict) -> dict:
    report = {
        "stage": "7M",
        "version": STAGE7M_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "PASS",
        "preflight": preflight,
        "contract": stage7m_contract(),
        "docker_health": docker_health,
        "acceptance_smoke": smoke,
        "api_url": f"http://127.0.0.1:{DEFAULT_PORT}",
        "workbench_url": f"http://127.0.0.1:{DEFAULT_PORT}/workbench",
        "cloud_mutation": False,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    SUCCESS_PATH.write_text(report["generated_at"] + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run PharmStock Stage 7M operational API")
    parser.add_argument("--execute", action="store_true", help="apply/start local Stage 7M")
    parser.add_argument("--no-build", action="store_true", help="reuse Stage 7M API image")
    args = parser.parse_args()

    preflight = _preflight()
    print(f"=== PharmStock V2 / Stage 7M Operational Decision API v{STAGE7M_VERSION} ===")
    print(f"Stage 7L status:          {preflight['stage7l_status']}")
    print(f"Stage 7L worker:          {preflight['stage7l_worker_status']}")
    print("API authentication:       API KEY + RBAC / DENY BY DEFAULT")
    print("Operational workbench:    ENABLED")
    print("Human approval:           REQUIRED")
    print("Automatic supplier pick:  DISABLED")
    print("Automatic PO creation:    BLOCKED / NO API ENDPOINT")
    print("Audit mutation:            APPEND ONLY FOR OPERATIONAL ROLES")
    print("BigQuery writes:           NONE")
    print("Cloud mutation:            NO")

    if not args.execute:
        print("Runtime mutation:          NO / DRY RUN")
        print("STAGE_7M_DRY_RUN_STATUS=PASS")
        return

    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.unlink(missing_ok=True)
    SMOKE_PATH.unlink(missing_ok=True)
    SUCCESS_PATH.unlink(missing_ok=True)

    print("Starting governed-decision dependencies...")
    _compose(
        "up",
        "-d",
        "postgres",
        "kafka",
        "connect",
        "mlflow",
        "model-serving",
        "stage7k5-online",
        "stage7l-workflow",
    )
    upstream_health = _wait_container_health(
        "pharmstock-stage7l-workflow",
        label="Stage 7L workflow",
        timeout_seconds=180,
    )
    print(f"Stage 7L readiness:       {upstream_health.upper()}")

    print("Applying Stage 7M least-privilege API boundary + read model...")
    _apply_schema()
    if not args.no_build:
        print("Building Stage 7M API image...")
        _compose("build", "stage7m-api")

    print("Starting operational API + workbench...")
    _compose("up", "-d", "--force-recreate", "stage7m-api")
    docker_health = _wait_container_health(
        "pharmstock-stage7m-api",
        label="Stage 7M API",
    )
    print("Running non-mutating API/RBAC/governance acceptance smoke...")
    smoke = _acceptance_smoke()
    report = _persist(preflight, docker_health, smoke)

    health = smoke["health"]
    summary = smoke["summary"]
    print("Stage 7M verification:")
    print(f"  API Docker health:           {docker_health.upper()}")
    print("  Unauthenticated API read:    BLOCKED")
    print("  Viewer mutation:             BLOCKED")
    print("  Procurement write privilege: BLOCKED")
    print("  Automatic PO endpoint:       NONE")
    print("  Workbench:                   READY")
    print(f"  Active decision cases:       {summary.get('active_cases', 'n/a')}")
    print(f"  High-priority cases:         {summary.get('high_priority_cases', 'n/a')}")
    print(f"  Stage 7L upstream:           {health.get('stage7l', {}).get('status')}")
    print("  BigQuery writes:             NONE")
    print("  Cloud mutation:              NO")
    if report["status"] != "PASS":
        raise RuntimeError("Stage 7M persisted report is not PASS")
    print("STAGE_7M_API_STATUS=PASS")
    print("STAGE_7M_RBAC_STATUS=PASS")
    print("STAGE_7M_GOVERNANCE_STATUS=PASS")
    print("STAGE_7M_WORKBENCH_STATUS=PASS")
    print("STAGE_7M_STATUS=PASS")


if __name__ == "__main__":
    main()
