"""Vertex-compatible single-model prediction container entry point.

The image is built only from a locally exported, scientifically accepted model
artifact. This module performs no cloud access and supports Vertex custom
container request/health routes when deployed later.
"""

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
MODEL_KEY = os.getenv("PHARMSTOCK_VERTEX_MODEL_KEY", "demand_forecast").strip()
MODEL_DIR = Path(os.getenv("PHARMSTOCK_MODEL_DIR", "/models"))
MODEL_PATH = MODEL_DIR / f"{MODEL_KEY}.joblib"

app = FastAPI(title="PharmStock Vertex Prediction Adapter", version=APP_VERSION)
_model: Any | None = None
_features: list[str] = []
_outputs: list[str] = []


class VertexRequest(BaseModel):
    instances: list[dict[str, float | int]]


def _load() -> None:
    global _model, _features, _outputs
    if not MODEL_PATH.is_file():
        raise RuntimeError(f"model artifact not found: {MODEL_PATH}")
    _model = joblib.load(MODEL_PATH)
    _features = [str(item) for item in getattr(_model, "feature_names_in_", [])]
    _outputs = [str(item) for item in getattr(_model, "output_names_", [])]


@app.on_event("startup")
def startup() -> None:
    _load()


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "healthy" if _model is not None else "degraded",
        "model_key": MODEL_KEY,
        "features": _features,
        "outputs": _outputs,
    }


@app.post("/predict")
def predict(payload: VertexRequest) -> dict[str, object]:
    if _model is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    if not payload.instances or len(payload.instances) > 1000:
        raise HTTPException(status_code=422, detail="instances must contain 1..1000 rows")
    missing = sorted(
        {feature for feature in _features if any(feature not in row for row in payload.instances)}
    )
    if missing:
        raise HTTPException(status_code=422, detail={"missing_features": missing})
    frame = pd.DataFrame(payload.instances)
    if _features:
        frame = frame.loc[:, _features]
    for column in frame.columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame.isna().any().any():
        raise HTTPException(status_code=422, detail="features must be finite numeric values")
    raw = np.asarray(_model.predict(frame))
    if raw.ndim == 2:
        predictions: object = [[float(item) for item in row] for row in raw]
        finite = all(math.isfinite(item) for row in predictions for item in row)
    else:
        predictions = [float(item) for item in raw]
        finite = all(math.isfinite(item) for item in predictions)
    if not finite:
        raise HTTPException(status_code=500, detail="non-finite prediction")
    response: dict[str, object] = {"predictions": predictions}
    if hasattr(_model, "predict_proba"):
        probability = np.asarray(_model.predict_proba(frame))
        if probability.ndim == 2 and probability.shape[1] >= 2:
            response["probabilities"] = [float(item) for item in probability[:, 1]]
    if _outputs:
        response["outputs"] = _outputs
    return response
