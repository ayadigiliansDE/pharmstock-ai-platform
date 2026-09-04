"""Export a local, immutable cloud build context without uploading anything."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

MODEL_KEYS = (
    "demand_forecast",
    "stockout_risk",
    "reorder_recommendation",
    "expiry_slow_moving_risk",
)
SOURCE_MODELS = Path("artifacts/stage7k/models")
OUTPUT = Path("artifacts/stage7k/cloud_bundle")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Stage 7K local cloud build context")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    success = Path("artifacts/stage7k/_SCIENTIFIC_VALIDATION_PASS")
    if not success.is_file():
        raise RuntimeError("cloud bundle export requires Stage 7K scientific validation PASS")
    missing = [key for key in MODEL_KEYS if not (SOURCE_MODELS / f"{key}.joblib").is_file()]
    if missing:
        raise RuntimeError(f"missing champion model artifacts: {missing}")
    if OUTPUT.exists():
        if not args.replace:
            raise RuntimeError(f"cloud bundle already exists: {OUTPUT}; use --replace")
        shutil.rmtree(OUTPUT)
    (OUTPUT / "models").mkdir(parents=True)
    manifest_models = []
    for key in MODEL_KEYS:
        source = SOURCE_MODELS / f"{key}.joblib"
        destination = OUTPUT / "models" / source.name
        shutil.copy2(source, destination)
        manifest_models.append(
            {"model_key": key, "file": destination.name, "sha256": _sha256(destination)}
        )
    package_dir = OUTPUT / "ml" / "stage7k"
    package_dir.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "ml" / "__init__.py").write_text("", encoding="utf-8")
    for name in ("__init__.py", "vertex_serve.py", "cloud_serve.py", "models.py"):
        shutil.copy2(Path("ml/stage7k") / name, package_dir / name)
    (OUTPUT / "requirements.txt").write_text(
        "fastapi==0.116.1\nuvicorn[standard]==0.35.0\n"
        "scikit-learn==1.7.2\npandas==2.3.2\nnumpy==2.3.2\njoblib==1.5.2\n",
        encoding="utf-8",
    )
    (OUTPUT / "Dockerfile.vertex").write_text(
        "FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\n"
        "RUN pip install --no-cache-dir -r requirements.txt\nCOPY models /models\n"
        "COPY ml /app/ml\nENV PYTHONPATH=/app\nENV PHARMSTOCK_MODEL_DIR=/models\n"
        "CMD [\"uvicorn\",\"ml.stage7k.vertex_serve:app\",\"--host\","
        "\"0.0.0.0\",\"--port\",\"8080\"]\n",
        encoding="utf-8",
    )
    (OUTPUT / "Dockerfile.decision").write_text(
        "FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\n"
        "RUN pip install --no-cache-dir -r requirements.txt\nCOPY models /models\n"
        "COPY ml /app/ml\nENV PYTHONPATH=/app\nENV PHARMSTOCK_MODEL_DIR=/models\n"
        "CMD [\"uvicorn\",\"ml.stage7k.cloud_serve:app\",\"--host\","
        "\"0.0.0.0\",\"--port\",\"8080\"]\n",
        encoding="utf-8",
    )
    manifest = {
        "stage": "7K.4",
        "generated_at": datetime.now(UTC).isoformat(),
        "cloud_mutation": False,
        "models": manifest_models,
        "vertex_targets": ["demand_forecast", "stockout_risk"],
        "cloud_run_targets": ["reorder_recommendation", "expiry_slow_moving_risk"],
    }
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"Cloud build context: {OUTPUT}")
    print("Artifact upload:     NONE")
    print("Cloud deployment:    NONE")
    print("STAGE_7K4_LOCAL_EXPORT_STATUS=PASS")


if __name__ == "__main__":
    main()
