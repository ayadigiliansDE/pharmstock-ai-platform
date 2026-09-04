"""Serializable Stage 7K predictive and prescriptive model wrappers."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin, RegressorMixin

DEMAND_HORIZONS = (1, 7, 14, 30)
STOCKOUT_FEATURES = [
    "available_units",
    "requested_avg_7",
    "requested_avg_28",
    "requested_stddev_28",
    "lost_rate_28",
    "stockout_rate_28",
    "supplier_lead_time_days",
    "supplier_reliability",
    "day_of_week",
    "month_of_year",
]
REORDER_FEATURES = [
    "available_units",
    "avg_daily_requested_units",
    "demand_stddev_units",
    "supplier_lead_time_days",
    "supplier_reliability",
    "inbound_units",
]
EXPIRY_FEATURES = [
    "days_to_expiry",
    "quantity_on_hand",
    "avg_daily_units_sold",
    "demand_stddev_units",
]


def _numeric(frame: pd.DataFrame, column: str) -> np.ndarray:
    return (
        pd.to_numeric(frame[column], errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0.0)
        .to_numpy(dtype=float)
    )


class MultiHorizonDemandModel(RegressorMixin, BaseEstimator):
    """Conservative multi-horizon demand forecast with a baseline safety fallback.

    Each horizon owns an ML estimator plus a validation-selected baseline and blend
    weight. A weight of zero intentionally deploys the statistically stronger naive
    baseline for that horizon instead of forcing a weaker ML forecast into production.
    """

    def __init__(
        self,
        estimators: dict[int, Any] | None = None,
        feature_names: list[str] | None = None,
        baseline_names: dict[int, str] | None = None,
        blend_weights: dict[int, float] | None = None,
    ):
        self.estimators = estimators or {}
        self.feature_names = feature_names or []
        self.baseline_names = baseline_names or {}
        self.blend_weights = blend_weights or {}
        self.horizons = tuple(sorted(int(value) for value in self.estimators))
        self.feature_names_in_ = np.asarray(self.feature_names, dtype=object)
        self.output_names_ = [f"demand_{horizon}d" for horizon in self.horizons]

    def fit(self, x: pd.DataFrame, y: Any = None) -> MultiHorizonDemandModel:
        self.feature_names_in_ = np.asarray(list(pd.DataFrame(x).columns), dtype=object)
        return self

    @staticmethod
    def _baseline(frame: pd.DataFrame, horizon: int, name: str) -> np.ndarray:
        if name == "recent_7d_mean":
            daily = _numeric(frame, "requested_avg_7")
        elif name == "recent_28d_mean":
            daily = _numeric(frame, "requested_avg_28")
        elif name == "persistence":
            daily = _numeric(frame, "requested_units")
        else:
            raise ValueError(f"unknown demand baseline: {name}")
        return np.maximum(daily * float(horizon), 0.0)

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        frame = pd.DataFrame(x).loc[:, list(self.feature_names_in_)]
        baseline_names = getattr(self, "baseline_names", {}) or {}
        blend_weights = getattr(self, "blend_weights", {}) or {}
        columns: list[np.ndarray] = []
        for horizon in self.horizons:
            ml_prediction = np.maximum(
                np.asarray(self.estimators[horizon].predict(frame), dtype=float),
                0.0,
            )
            baseline_name = baseline_names.get(horizon)
            if baseline_name is None:
                # Backward compatibility for pre-v0.34.0 registered artifacts.
                columns.append(ml_prediction)
                continue
            baseline_prediction = self._baseline(frame, horizon, baseline_name)
            weight = float(np.clip(blend_weights.get(horizon, 0.0), 0.0, 1.0))
            prediction = baseline_prediction + weight * (ml_prediction - baseline_prediction)
            columns.append(np.maximum(prediction, 0.0))
        if not columns:
            return np.empty((len(frame), 0), dtype=float)
        return np.column_stack(columns)


class CalibratedThresholdClassifier(ClassifierMixin, BaseEstimator):
    """Binary classifier with Platt-style calibration and an operating threshold."""

    def __init__(
        self,
        estimator: Any,
        calibrator: Any,
        threshold: float,
        feature_names: list[str],
    ):
        self.estimator = estimator
        self.calibrator = calibrator
        self.threshold = float(threshold)
        self.feature_names = list(feature_names)
        self.feature_names_in_ = np.asarray(self.feature_names, dtype=object)
        self.classes_ = np.asarray([0, 1], dtype=int)

    def fit(self, x: pd.DataFrame, y: Any = None) -> CalibratedThresholdClassifier:
        self.feature_names_in_ = np.asarray(list(pd.DataFrame(x).columns), dtype=object)
        return self

    def _raw_positive(self, x: pd.DataFrame) -> np.ndarray:
        frame = pd.DataFrame(x).loc[:, list(self.feature_names_in_)]
        raw = np.asarray(self.estimator.predict_proba(frame)[:, 1], dtype=float)
        return np.clip(raw, 1e-6, 1.0 - 1e-6)

    def predict_proba(self, x: pd.DataFrame) -> np.ndarray:
        raw = self._raw_positive(x)
        logits = np.log(raw / (1.0 - raw)).reshape(-1, 1)
        positive = np.asarray(self.calibrator.predict_proba(logits)[:, 1], dtype=float)
        positive = np.clip(positive, 0.0, 1.0)
        return np.column_stack((1.0 - positive, positive))

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        return (self.predict_proba(x)[:, 1] >= self.threshold).astype(int)


class ReorderPolicyModel(RegressorMixin, BaseEstimator):
    """Service-level replenishment policy exposed through the standard model API."""

    def __init__(self, review_period_days: float = 7.0, service_z: float = 1.65):
        self.review_period_days = review_period_days
        self.service_z = service_z

    def fit(self, x: pd.DataFrame, y: Any = None) -> ReorderPolicyModel:
        self.feature_names_in_ = np.asarray(REORDER_FEATURES, dtype=object)
        return self

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        frame = pd.DataFrame(x).loc[:, REORDER_FEATURES]
        available = np.maximum(_numeric(frame, "available_units"), 0.0)
        mean_daily = np.maximum(_numeric(frame, "avg_daily_requested_units"), 0.0)
        sigma_daily = np.maximum(_numeric(frame, "demand_stddev_units"), 0.0)
        reliability = np.clip(_numeric(frame, "supplier_reliability"), 0.50, 1.0)
        lead_days = np.maximum(_numeric(frame, "supplier_lead_time_days"), 1.0) / reliability
        inbound = np.maximum(_numeric(frame, "inbound_units"), 0.0)
        protection_days = lead_days + max(float(self.review_period_days), 0.0)
        cycle_demand = mean_daily * protection_days
        safety_stock = (
            max(float(self.service_z), 0.0) * sigma_daily * np.sqrt(protection_days)
        )
        effective_supply = available + inbound * reliability
        recommendation = np.maximum(cycle_demand + safety_stock - effective_supply, 0.0)
        return np.ceil(recommendation).astype(float)


class ExpiryRiskModel(ClassifierMixin, BaseEstimator):
    """Probability that current batch inventory remains unsold at expiry."""

    def __init__(self, threshold: float = 0.50):
        self.threshold = threshold

    def fit(self, x: pd.DataFrame, y: Any = None) -> ExpiryRiskModel:
        self.feature_names_in_ = np.asarray(EXPIRY_FEATURES, dtype=object)
        self.classes_ = np.asarray([0, 1], dtype=int)
        return self

    def predict_proba(self, x: pd.DataFrame) -> np.ndarray:
        frame = pd.DataFrame(x).loc[:, EXPIRY_FEATURES]
        days = _numeric(frame, "days_to_expiry")
        on_hand = np.maximum(_numeric(frame, "quantity_on_hand"), 0.0)
        velocity = np.maximum(_numeric(frame, "avg_daily_units_sold"), 0.0)
        sigma_daily = np.maximum(_numeric(frame, "demand_stddev_units"), 0.0)
        mean_sales = velocity * np.maximum(days, 0.0)
        sigma_sales = sigma_daily * np.sqrt(np.maximum(days, 1.0))
        positive = np.zeros(len(frame), dtype=float)
        expired = (days <= 0.0) & (on_hand > 0.0)
        deterministic = (sigma_sales <= 1e-9) & ~expired
        positive[expired] = 1.0
        positive[deterministic] = (
            mean_sales[deterministic] < on_hand[deterministic]
        ).astype(float)
        stochastic = (~expired) & (~deterministic) & (on_hand > 0.0)
        if np.any(stochastic):
            z = (
                on_hand[stochastic] - 0.5 - mean_sales[stochastic]
            ) / sigma_sales[stochastic]
            positive[stochastic] = np.asarray(
                [0.5 * (1.0 + math.erf(float(value) / math.sqrt(2.0))) for value in z],
                dtype=float,
            )
        positive = np.where(on_hand <= 0.0, 0.0, positive)
        positive = np.clip(positive, 0.0, 1.0)
        return np.column_stack((1.0 - positive, positive))

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        return (self.predict_proba(x)[:, 1] >= float(self.threshold)).astype(int)
