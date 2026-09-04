"""Stage 7K launcher with strict production-quality champion gating."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib import error, request

from pharmstock.ml.stage7k import (
    MODEL_SPECS,
    STAGE7J_SUCCESS,
    STAGE7K_ROOT,
    STAGE7K_SUCCESS,
    STAGE7K_VERSION,
    config_from_environment,
    stage7k_contract,
    storage_status,
)

COMPOSE_FILE = Path("infra/docker/docker-compose.stage7k.yml")
EXPECTED_GOLD_MODELS = {
    "mart7h_product_daily_performance",
    "mart7h_branch_daily_operations",
    "mart7h_supplier_performance",
}
EXPECTED_CURRENT_VIEWS = {
    "inventory__inventory_position",
    "inventory__stock_batch",
    "inventory__stock_movement",
    "pos__demand_attempt",
    "procurement__purchase_order",
    "procurement__purchase_order_line",
    "procurement__supplier",
}


def _client(project_id: str):
    try:
        from google.cloud import bigquery
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError("google-cloud-bigquery is required; install the gcp extra") from exc
    return bigquery.Client(project=project_id)


def _storage_bytes(client) -> int:
    total = 0
    for dataset in client.list_datasets():
        for table_item in client.list_tables(dataset.reference):
            table = client.get_table(table_item.reference)
            total += int(table.num_bytes or 0)
    return total


def _preflight(config) -> dict[str, object]:
    if not STAGE7J_SUCCESS.is_file():
        raise RuntimeError("Stage 7K requires artifacts/stage7j/_SUCCESS")
    client = _client(str(config.project_id))
    storage_gib = _storage_bytes(client) / 1024**3
    status = storage_status(storage_gib, config)
    if status == "STOP":
        raise RuntimeError(
            f"BigQuery storage guard STOP: {storage_gib:.3f} GiB >= {config.hard_stop_gib:.3f} GiB"
        )
    gold = {item.table_id for item in client.list_tables(config.gold_dataset)}
    current = {item.table_id for item in client.list_tables(config.current_dataset)}
    missing_gold = EXPECTED_GOLD_MODELS - gold
    missing_current = EXPECTED_CURRENT_VIEWS - current
    if missing_gold:
        raise RuntimeError(f"missing Stage 7H Gold models: {sorted(missing_gold)}")
    if missing_current:
        raise RuntimeError(f"missing Stage 7I current-state views: {sorted(missing_current)}")
    return {
        "storage_gib": storage_gib,
        "storage_status": status,
        "gold_models": len(EXPECTED_GOLD_MODELS),
        "current_feature_views": len(EXPECTED_CURRENT_VIEWS),
    }


def _compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = ["docker", "compose", "-f", str(COMPOSE_FILE), *args]
    environment = os.environ.copy()
    # Preserve the other project services while suppressing Compose's harmless
    # orphan warning. We intentionally do not remove or mutate those containers.
    environment.setdefault("COMPOSE_IGNORE_ORPHANS", "true")
    return subprocess.run(command, check=check, text=True, env=environment)


def _wait_http(url: str, *, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with request.urlopen(url, timeout=5) as response:
                if 200 <= int(response.status) < 300:
                    return
        except (OSError, error.URLError) as exc:
            last_error = exc
        time.sleep(3)
    raise RuntimeError(f"timed out waiting for {url}: {last_error}")


def _wait_json(url: str, *, timeout_seconds: int, required_key: str | None = None) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with request.urlopen(url, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if required_key is None or required_key in payload:
                return payload
        except (OSError, ValueError, error.URLError) as exc:
            last_error = exc
        time.sleep(3)
    raise RuntimeError(f"timed out waiting for {url}: {last_error}")


def _post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _run_training() -> None:
    _compose("run", "--rm", "trainer", "python", "/workspace/ml/stage7k/train.py")


def _smoke_sample(model_key: str, features: list[str]) -> dict[str, float]:
    defaults = {feature: 1.0 for feature in features}
    if model_key == "stockout_risk":
        defaults.update(
            {
                "available_units": 12.0,
                "requested_avg_7": 8.0,
                "requested_avg_28": 7.5,
                "requested_stddev_28": 2.0,
                "lost_rate_28": 0.02,
                "stockout_rate_28": 0.01,
                "supplier_lead_time_days": 3.0,
                "supplier_reliability": 0.95,
                "day_of_week": 3.0,
                "month_of_year": 8.0,
            }
        )
    elif model_key == "reorder_recommendation":
        defaults.update(
            {
                "available_units": 12.0,
                "avg_daily_requested_units": 8.0,
                "demand_stddev_units": 2.0,
                "supplier_lead_time_days": 3.0,
                "supplier_reliability": 0.95,
                "inbound_units": 0.0,
            }
        )
    elif model_key == "expiry_slow_moving_risk":
        defaults.update(
            {
                "days_to_expiry": 90.0,
                "quantity_on_hand": 40.0,
                "avg_daily_units_sold": 1.0,
                "demand_stddev_units": 0.5,
            }
        )
    return defaults


def _verify_serving(serving_uri: str) -> dict[str, object]:
    health = _wait_json(f"{serving_uri}/health", timeout_seconds=240, required_key="loaded_models")
    models = _wait_json(f"{serving_uri}/models", timeout_seconds=60, required_key="models")
    rows = models.get("models", [])
    expected = len(MODEL_SPECS)
    if (
        health.get("status") != "healthy"
        or int(health.get("loaded_models", 0)) != expected
        or int(health.get("production_ready_models", 0)) != expected
    ):
        raise RuntimeError(f"serving production-readiness verification failed: {health}")
    if len(rows) != expected:
        raise RuntimeError(f"model serving returned {len(rows)} models, expected {expected}")

    smoke_predictions: list[dict[str, object]] = []
    for row in rows:
        if not row.get("version") or row.get("quality_gate") != "PASS":
            raise RuntimeError(f"model is not a quality-gated champion: {row}")
        if not bool(row.get("production_ready")):
            raise RuntimeError(f"model is not production-ready: {row}")
        model_key = str(row["key"])
        features = [str(item) for item in row.get("features", [])]
        sample = _smoke_sample(model_key, features)
        prediction = _post_json(f"{serving_uri}/predict/{model_key}", {"records": [sample]})
        values = prediction.get("prediction", [])
        if not isinstance(values, list) or len(values) != 1:
            raise RuntimeError(f"serving smoke prediction failed for {model_key}: {prediction}")
        if model_key == "demand_forecast":
            prediction_row = values[0]
            if not isinstance(prediction_row, list) or len(prediction_row) != 4:
                raise RuntimeError(f"demand model did not return 4 horizons: {prediction}")
            if not all(
                math.isfinite(float(item)) and float(item) >= 0.0 for item in prediction_row
            ):
                raise RuntimeError(f"invalid multi-horizon demand prediction: {prediction}")
            value: object = [float(item) for item in prediction_row]
        else:
            value = float(values[0])
            if not math.isfinite(value):
                raise RuntimeError(f"non-finite serving prediction for {model_key}: {prediction}")
        probabilities = prediction.get("probability")
        if model_key in {"stockout_risk", "expiry_slow_moving_risk"}:
            if not isinstance(probabilities, list) or len(probabilities) != 1:
                raise RuntimeError(f"risk model returned no probability: {prediction}")
            probability = float(probabilities[0])
            if not 0.0 <= probability <= 1.0:
                raise RuntimeError(f"risk probability outside [0,1]: {prediction}")
        smoke_predictions.append(
            {
                "model_key": model_key,
                "version": row["version"],
                "prediction": value,
                "production_ready": True,
            }
        )
    return {"health": health, "models": rows, "smoke_predictions": smoke_predictions}


def _persist(report: dict[str, object]) -> None:
    STAGE7K_ROOT.mkdir(parents=True, exist_ok=True)
    (STAGE7K_ROOT / "stage7k_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    STAGE7K_SUCCESS.write_text(str(report["generated_at"]) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run PharmStock Stage 7K ML platform")
    parser.add_argument(
        "--execute", action="store_true", help="validate/train/promote/start serving"
    )
    parser.add_argument("--no-build", action="store_true", help="reuse the existing Stage 7K image")
    args = parser.parse_args()

    config = config_from_environment()
    preflight = _preflight(config)
    print(
        "=== PharmStock V2 / Stage 7K Scientific Validation + "
        f"Cloud-Ready Hardening v{STAGE7K_VERSION} ==="
    )
    print(f"Project:                {config.project_id}")
    print("BigQuery mode:          READ ONLY")
    print("BigQuery writes:        NONE")
    print("Raw baseline copy:      NONE")
    print("Feature tables created: NONE")
    print(f"Storage now:            {preflight['storage_gib']:.3f} GiB")
    print(f"Storage guard:          {preflight['storage_status']}")
    print("Champion gate:          STRICT / 4 of 4 scientific gates must PASS")
    print(f"Models planned:         {len(MODEL_SPECS)}")
    for spec in MODEL_SPECS:
        print(f"  - {spec.key} [{spec.model_kind}] -> {spec.registered_name}")

    if not args.execute:
        print("Cloud mutation:         NO / DRY RUN")
        print("STAGE_7K_SCIENTIFIC_DRY_RUN_STATUS=PASS")
        return

    # Fail closed: an older champion set must not remain externally served while
    # strict quality validation is running. Registry history is preserved.
    STAGE7K_SUCCESS.unlink(missing_ok=True)
    _compose("stop", "model-serving", check=False)

    if not args.no_build:
        print("Building Stage 7K ML image...")
        _compose("build", "mlflow", "trainer", "model-serving")
    print("Starting MLflow tracking + registry...")
    _compose("up", "-d", "mlflow")
    _wait_http(f"{config.mlflow_uri}/health", timeout_seconds=300)
    print(f"MLflow control plane:   HEALTHY ({config.mlflow_uri})")

    print("Training candidates + strict quality validation...")
    _run_training()

    print("Starting production-gated multi-model inference API...")
    _compose("up", "-d", "--force-recreate", "model-serving")
    serving = _verify_serving(config.serving_uri)
    print(f"Serving API:            HEALTHY ({config.serving_uri})")
    print(f"Production champions:   {len(serving['models'])}/{len(MODEL_SPECS)}")
    print(f"Inference smoke tests:  {len(serving['smoke_predictions'])}/{len(MODEL_SPECS)} PASS")

    report = {
        "stage": "7K",
        "hardening": f"v{STAGE7K_VERSION}",
        "generated_at": datetime.now(UTC).isoformat(),
        "project_id": config.project_id,
        "bigquery_writes": False,
        "raw_baseline_copy": False,
        "feature_tables_created": False,
        "storage_gib_before": preflight["storage_gib"],
        "storage_guard": preflight["storage_status"],
        "strict_champion_gate": True,
        "mlflow_uri": config.mlflow_uri,
        "serving_uri": config.serving_uri,
        "registered_models": serving["models"],
        "contract": stage7k_contract(),
    }
    _persist(report)
    print("STAGE_7K_SCIENTIFIC_VALIDATION_STATUS=PASS")
    print("STAGE_7K_MODEL_QUALITY_STATUS=PASS")
    print("STAGE_7K_MLFLOW_STATUS=PASS")
    print("STAGE_7K_REGISTRY_STATUS=PASS")
    print("STAGE_7K_SERVING_STATUS=PASS")
    print("STAGE_7K_PRODUCTION_READINESS_STATUS=PASS")
    print("STAGE_7K_STATUS=PASS")


if __name__ == "__main__":
    main()
