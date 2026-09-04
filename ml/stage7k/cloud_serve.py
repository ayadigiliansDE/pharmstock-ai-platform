"""Cloud Run compatible stateless serving adapter for decision engines."""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

APP_VERSION = "0.34.2"
MODEL_DIR = Path(os.getenv("PHARMSTOCK_MODEL_DIR", "/models"))
DECISION_MODELS = ("reorder_recommendation", "expiry_slow_moving_risk")
app = FastAPI(title="PharmStock Decision Engine", version=APP_VERSION)
_models: dict[str, Any] = {}
_features: dict[str, list[str]] = {}


class PredictionRequest(BaseModel):
    records: list[dict[str, float | int]]


@app.on_event("startup")
def startup() -> None:
    _models.clear()
    _features.clear()
    for key in DECISION_MODELS:
        path = MODEL_DIR / f"{key}.joblib"
        if not path.is_file():
            continue
        model = joblib.load(path)
        _models[key] = model
        _features[key] = [str(item) for item in getattr(model, "feature_names_in_", [])]


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "healthy" if len(_models) == len(DECISION_MODELS) else "degraded",
        "loaded_models": sorted(_models),
    }


@app.post("/predict/{model_key}")
def predict(model_key: str, payload: PredictionRequest) -> dict[str, object]:
    if model_key not in _models:
        raise HTTPException(status_code=404, detail=f"decision model unavailable: {model_key}")
    if not payload.records or len(payload.records) > 1000:
        raise HTTPException(status_code=422, detail="records must contain 1..1000 rows")
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
    raw = np.asarray(model.predict(frame))
    values = [float(item) for item in raw]
    if not all(math.isfinite(item) for item in values):
        raise HTTPException(status_code=500, detail="non-finite prediction")
    response: dict[str, object] = {"model_key": model_key, "prediction": values}
    if hasattr(model, "predict_proba"):
        probability = np.asarray(model.predict_proba(frame))
        if probability.ndim == 2 and probability.shape[1] >= 2:
            response["probability"] = [float(item) for item in probability[:, 1]]
    return response
