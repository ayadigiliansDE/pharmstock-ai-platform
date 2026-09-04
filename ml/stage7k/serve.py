"""Production-gated multi-model inference API backed by MLflow champion aliases."""

from __future__ import annotations

import math
import os
from typing import Any

import mlflow
import mlflow.sklearn
import pandas as pd
from fastapi import FastAPI, HTTPException
from mlflow import MlflowClient
from pydantic import BaseModel

from pharmstock.ml.stage7k import MODEL_SPECS, STAGE7K_VERSION

mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000"))
app = FastAPI(title="PharmStock Stage 7K Model Serving", version=STAGE7K_VERSION)
_models: dict[str, Any] = {}
_versions: dict[str, str] = {}
_features: dict[str, list[str]] = {}
_metadata: dict[str, dict[str, object]] = {}
_outputs: dict[str, list[str]] = {}


class PredictionRequest(BaseModel):
    records: list[dict[str, float | int]]


def _load_models() -> None:
    client = MlflowClient()
    _models.clear()
    _versions.clear()
    _features.clear()
    _metadata.clear()
    _outputs.clear()
    for spec in MODEL_SPECS:
        try:
            version = client.get_model_version_by_alias(spec.registered_name, "champion")
        except Exception:
            continue
        production_ready = str(version.tags.get("production_ready", "false")).lower() == "true"
        if not production_ready:
            continue
        model = mlflow.sklearn.load_model(f"models:/{spec.registered_name}@champion")
        features = [str(item) for item in getattr(model, "feature_names_in_", [])]
        _models[spec.key] = model
        _versions[spec.key] = str(version.version)
        _features[spec.key] = features
        _outputs[spec.key] = [str(item) for item in getattr(model, "output_names_", [])]
        threshold = getattr(model, "threshold", None)
        if threshold is not None:
            try:
                threshold = float(threshold)
            except (TypeError, ValueError):
                threshold = None
        _metadata[spec.key] = {
            "model_kind": version.tags.get("model_kind", spec.model_kind),
            "quality_gate": version.tags.get("quality_gate", "unknown"),
            "production_ready": production_ready,
            "threshold": threshold,
        }


@app.on_event("startup")
def startup() -> None:
    _load_models()


@app.get("/health")
def health() -> dict[str, object]:
    ready = len(_models)
    expected = len(MODEL_SPECS)
    return {
        "status": "healthy" if ready == expected else "degraded",
        "loaded_models": ready,
        "production_ready_models": ready,
        "expected_models": expected,
        "strict_quality_gate": True,
    }


@app.get("/models")
def models() -> dict[str, object]:
    return {
        "models": [
            {
                "key": spec.key,
                "registered_name": spec.registered_name,
                "version": _versions.get(spec.key),
                "alias": "champion" if spec.key in _models else None,
                "features": _features.get(spec.key, []),
                "outputs": _outputs.get(spec.key, []),
                "model_kind": _metadata.get(spec.key, {}).get("model_kind", spec.model_kind),
                "quality_gate": _metadata.get(spec.key, {}).get("quality_gate"),
                "production_ready": bool(
                    _metadata.get(spec.key, {}).get("production_ready", False)
                ),
                "threshold": _metadata.get(spec.key, {}).get("threshold"),
            }
            for spec in MODEL_SPECS
        ]
    }


@app.post("/reload")
def reload_models() -> dict[str, object]:
    _load_models()
    return health()


@app.post("/predict/{model_key}")
def predict(model_key: str, payload: PredictionRequest) -> dict[str, object]:
    if model_key not in _models:
        raise HTTPException(
            status_code=503,
            detail=f"model is unavailable or not production-ready: {model_key}",
        )
    if not payload.records:
        raise HTTPException(status_code=422, detail="records cannot be empty")
    if len(payload.records) > 1_000:
        raise HTTPException(status_code=422, detail="maximum 1000 records per request")
    required = _features[model_key]
    missing = sorted(
        {feature for feature in required if any(feature not in row for row in payload.records)}
    )
    if missing:
        raise HTTPException(status_code=422, detail={"missing_features": missing})
    frame = pd.DataFrame(payload.records)
    if required:
        frame = frame.loc[:, required]
    for column in frame.columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame.isna().any().any():
        raise HTTPException(status_code=422, detail="features must be finite numeric values")
    model = _models[model_key]
    prediction = model.predict(frame)
    prediction_array = getattr(prediction, "ndim", 1)
    if prediction_array == 2:
        values = [[float(item) for item in row] for row in prediction]
        if not all(math.isfinite(item) for row in values for item in row):
            raise HTTPException(status_code=500, detail="model returned non-finite prediction")
    else:
        values = [float(value) for value in prediction]
        if not all(math.isfinite(value) for value in values):
            raise HTTPException(status_code=500, detail="model returned non-finite prediction")
    response: dict[str, object] = {
        "model_key": model_key,
        "version": _versions[model_key],
        "model_kind": _metadata[model_key]["model_kind"],
        "quality_gate": _metadata[model_key]["quality_gate"],
        "production_ready": True,
        "outputs": _outputs.get(model_key, []),
        "prediction": values,
    }
    if hasattr(model, "predict_proba"):
        probabilities = model.predict_proba(frame)
        if probabilities.shape[1] >= 2:
            response["probability"] = [float(value) for value in probabilities[:, 1]]
    return response
