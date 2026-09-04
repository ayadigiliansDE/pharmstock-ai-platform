"""Scientific validation, training and registry promotion for PharmStock Stage 7K.

v0.34.0 finalizes the Stage 7K acceptance gate as a production-style scientific
review: full-history temporal sampling, multi-horizon forecasting, observed
future stockout labels, historical replenishment replay and stochastic expiry
calibration. BigQuery is strictly read only.
"""

from __future__ import annotations

import json
import math
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import joblib
import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from google.cloud import bigquery
from mlflow import MlflowClient
from mlflow.models import infer_signature
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    fbeta_score,
    mean_absolute_error,
    mean_squared_error,
    precision_recall_curve,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)

from ml.stage7k.models import (
    DEMAND_HORIZONS,
    EXPIRY_FEATURES,
    REORDER_FEATURES,
    STOCKOUT_FEATURES,
    CalibratedThresholdClassifier,
    ExpiryRiskModel,
    MultiHorizonDemandModel,
    ReorderPolicyModel,
)
from pharmstock.ml.offline_history import (
    DEFAULT_OFFLINE_HISTORY_DAYS,
    MIN_OBSERVED_HISTORY_DAYS,
    OFFLINE_HISTORY_PROVENANCE,
    build_demand_history,
    build_stockout_history,
    persist_offline_history,
)
from pharmstock.ml.stage7k import (
    MODEL_SPECS,
    STAGE7K_ROOT,
    STAGE7K_VERSION,
    config_from_environment,
    demand_calibration_seed_sql,
    expiry_feature_sql,
    history_coverage_sql,
    product_temporal_feature_sql,
    stockout_calibration_seed_sql,
    stockout_supervised_feature_sql,
)

EXPERIMENT_NAME = "pharmstock-stage7k"
RANDOM_STATE = 20260826
MIN_ACCEPTANCE_ROWS = 1_000
MIN_TRAIN_POSITIVES = 100
MIN_VALIDATION_POSITIVES = 30
MIN_TEST_POSITIVES = 40
MIN_TOTAL_POSITIVES = 200
SYNTHETIC_BACKFILL_MAX_BLEND_WEIGHT = 0.15

SKOPS_TRUSTED_MODEL_TYPES = {
    "ml.stage7k.models.MultiHorizonDemandModel",
    "ml.stage7k.models.CalibratedThresholdClassifier",
    "ml.stage7k.models.ReorderPolicyModel",
    "ml.stage7k.models.ExpiryRiskModel",
}


def _trusted_skops_types(model: Any) -> list[str]:
    """Return the minimal explicit trust allowlist for internal model wrappers."""
    qualified_name = f"{type(model).__module__}.{type(model).__qualname__}"
    if qualified_name not in SKOPS_TRUSTED_MODEL_TYPES:
        raise RuntimeError(
            "refusing to serialize an unapproved custom model type with skops: "
            f"{qualified_name}"
        )
    return [qualified_name]


DEMAND_FEATURES = [
    "retail_price_egp",
    "selling_branches",
    "sales_transactions",
    "units_sold",
    "requested_units",
    "fulfilled_units",
    "lost_units",
    "fill_rate",
    "stockout_attempts",
    "net_sales_egp",
    "gross_profit_egp",
    "day_of_week",
    "month_of_year",
    "lost_rate",
    "requested_lag_1",
    "requested_lag_7",
    "requested_lag_14",
    "requested_lag_28",
    "requested_avg_7",
    "requested_avg_28",
    "requested_stddev_28",
    "stockout_avg_7",
    "demand_trend_7_28",
]


def _spec(key: str):
    return next(item for item in MODEL_SPECS if item.key == key)


def _clean_numeric(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = frame.loc[:, columns].copy()
    for column in columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    return result.replace([np.inf, -np.inf], np.nan).fillna(0.0).astype(float)


def _query_dataframe(client: bigquery.Client, sql: str, max_bytes: int) -> pd.DataFrame:
    job_config = bigquery.QueryJobConfig(maximum_bytes_billed=max_bytes, use_query_cache=True)
    job = client.query(
        sql,
        job_config=job_config,
        location=os.getenv("PHARMSTOCK_BQ_LOCATION", "EU"),
    )
    return job.result().to_dataframe(create_bqstorage_client=False)


def _time_split_three(
    frame: pd.DataFrame, *, embargo_days: int = 0
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Create chronological train/validation/test splits with a target embargo.

    For forward-looking labels, rows immediately before a split boundary are
    purged so their target window cannot reach into the next partition. This is
    essential for 30-day demand targets and 7-day stockout labels.
    """

    ordered_dates = sorted(pd.to_datetime(frame["business_date"]).dt.date.unique())
    if len(ordered_dates) < 30:
        raise RuntimeError("scientific validation requires at least 30 distinct dates")
    train_index = max(1, math.floor(len(ordered_dates) * 0.60)) - 1
    validation_index = max(train_index + 1, math.floor(len(ordered_dates) * 0.80)) - 1
    train_boundary = ordered_dates[train_index]
    validation_boundary = ordered_dates[min(validation_index, len(ordered_dates) - 2)]
    embargo = timedelta(days=max(int(embargo_days), 0))
    train_label_cutoff = train_boundary - embargo
    validation_label_cutoff = validation_boundary - embargo
    dates = pd.to_datetime(frame["business_date"]).dt.date
    train = frame.loc[dates <= train_label_cutoff].copy()
    validation = frame.loc[
        (dates > train_boundary) & (dates <= validation_label_cutoff)
    ].copy()
    test = frame.loc[dates > validation_boundary].copy()
    if min(len(train), len(validation), len(test)) < MIN_ACCEPTANCE_ROWS:
        raise RuntimeError(
            "purged temporal train/validation/test split is too small; "
            f"embargo_days={embargo_days}"
        )
    return train, validation, test


def _regression_metrics(y_true: pd.Series | np.ndarray, prediction: np.ndarray) -> dict[str, float]:
    y_array = np.asarray(y_true, dtype=float)
    pred = np.asarray(prediction, dtype=float)
    denominator = max(float(np.abs(y_array).sum()), 1.0)
    absolute_error = np.abs(y_array - pred)
    smape_denominator = np.maximum(np.abs(y_array) + np.abs(pred), 1e-9)
    mean_target = max(float(np.mean(np.abs(y_array))), 1e-9)
    return {
        "mae": float(mean_absolute_error(y_array, pred)),
        "rmse": float(mean_squared_error(y_array, pred) ** 0.5),
        "r2": float(r2_score(y_array, pred)),
        "wape": float(absolute_error.sum() / denominator),
        "smape": float(np.mean(2.0 * absolute_error / smape_denominator)),
        "median_ae": float(np.median(absolute_error)),
        "p90_ae": float(np.quantile(absolute_error, 0.90)),
        "bias": float(np.mean(pred - y_array)),
        "bias_pct_of_mean_target": float(np.mean(pred - y_array) / mean_target),
    }


def _paired_mae_improvement_ci(
    y_true: pd.Series | np.ndarray,
    model_prediction: np.ndarray,
    baseline_prediction: np.ndarray,
    *,
    repetitions: int = 200,
) -> dict[str, float]:
    """Bootstrap a paired confidence interval for MAE improvement."""

    y_array = np.asarray(y_true, dtype=float)
    model_error = np.abs(y_array - np.asarray(model_prediction, dtype=float))
    baseline_error = np.abs(y_array - np.asarray(baseline_prediction, dtype=float))
    improvement = baseline_error - model_error
    if len(improvement) < 2:
        return {"mean_absolute_error_gain": 0.0, "ci95_low": 0.0, "ci95_high": 0.0}
    rng = np.random.default_rng(RANDOM_STATE)
    estimates = np.empty(repetitions, dtype=float)
    for index in range(repetitions):
        sample = rng.integers(0, len(improvement), size=len(improvement))
        estimates[index] = float(np.mean(improvement[sample]))
    return {
        "mean_absolute_error_gain": float(np.mean(improvement)),
        "ci95_low": float(np.quantile(estimates, 0.025)),
        "ci95_high": float(np.quantile(estimates, 0.975)),
    }


def _demand_segment_metrics(
    frame: pd.DataFrame, y_true: pd.Series | np.ndarray, prediction: np.ndarray
) -> dict[str, dict[str, float]]:
    """Evaluate demand forecast error across demand-volume strata."""

    volume = pd.to_numeric(frame["requested_avg_28"], errors="coerce").fillna(0.0)
    try:
        buckets = pd.qcut(volume.rank(method="first"), q=4, labels=["q1", "q2", "q3", "q4"])
    except ValueError:
        return {}
    y_array = np.asarray(y_true, dtype=float)
    pred = np.asarray(prediction, dtype=float)
    report: dict[str, dict[str, float]] = {}
    for label in ["q1", "q2", "q3", "q4"]:
        mask = np.asarray(buckets == label)
        if not np.any(mask):
            continue
        report[label] = _regression_metrics(y_array[mask], pred[mask])
    return report


def _json_safe(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _register_candidate(
    *,
    model: Any,
    spec_key: str,
    features: list[str],
    metrics: dict[str, float],
    params: dict[str, object],
    quality: dict[str, object],
    x_example: pd.DataFrame,
    training_rows: int,
    test_rows: int,
    extra_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    spec = _spec(spec_key)
    tracking_client = MlflowClient()
    production_ready = bool(quality.get("production_ready", False))
    with mlflow.start_run(run_name=f"stage7k-scientific-{spec_key}") as run:
        mlflow.set_tags(
            {
                "stage": "7K",
                "hardening": f"v{STAGE7K_VERSION}",
                "model_key": spec.key,
                "registered_name": spec.registered_name,
                "model_kind": spec.model_kind,
                "bigquery_mode": "read_only",
                "source": spec.source,
                "target": spec.target,
                "production_ready": str(production_ready).lower(),
            }
        )
        mlflow.log_params({key: str(value) for key, value in params.items()})
        mlflow.log_param("training_rows", training_rows)
        mlflow.log_param("test_rows", test_rows)
        finite_metrics = {
            key: float(value) for key, value in metrics.items() if math.isfinite(float(value))
        }
        mlflow.log_metrics(finite_metrics)
        signature = infer_signature(x_example, model.predict(x_example))
        model_info = mlflow.sklearn.log_model(
            sk_model=model,
            name="model",
            input_example=x_example.head(3),
            signature=signature,
            serialization_format=mlflow.sklearn.SERIALIZATION_FORMAT_SKOPS,
            skops_trusted_types=_trusted_skops_types(model),
            code_paths=["/workspace/ml"],
        )
        metadata = {
            "model_key": spec.key,
            "registered_name": spec.registered_name,
            "model_kind": spec.model_kind,
            "features": features,
            "metrics": metrics,
            "quality": quality,
            "source": spec.source,
            "target": spec.target,
            "run_id": run.info.run_id,
            **(extra_metadata or {}),
        }
        mlflow.log_dict(_json_safe(metadata), "metadata/model.json")
        registered = mlflow.register_model(model_info.model_uri, spec.registered_name)
        version = str(registered.version)
        tracking_client.set_registered_model_alias(spec.registered_name, "candidate", version)
        for key, value in {
            "stage": "7K",
            "hardening": f"v{STAGE7K_VERSION}",
            "model_kind": spec.model_kind,
            "production_ready": str(production_ready).lower(),
            "quality_gate": str(quality.get("gate", "unknown")),
        }.items():
            tracking_client.set_model_version_tag(spec.registered_name, version, key, value)
        return {
            **metadata,
            "version": version,
            "alias": "candidate",
            "production_ready": production_ready,
        }


def _promote_all(results: list[dict[str, object]]) -> None:
    failed = [str(item["model_key"]) for item in results if not item["production_ready"]]
    if failed:
        raise RuntimeError(
            "strict scientific champion gate failed; no candidate set was promoted: "
            + ", ".join(failed)
        )
    client = MlflowClient()
    for result in results:
        name = str(result["registered_name"])
        version = str(result["version"])
        try:
            previous = client.get_model_version_by_alias(name, "champion")
            if str(previous.version) != version:
                client.set_registered_model_alias(name, "previous_champion", str(previous.version))
        except Exception:
            pass
        client.set_registered_model_alias(name, "champion", version)
        client.set_model_version_tag(name, version, "deployment_status", "champion")
        result["alias"] = "champion"


def _demand_baseline(frame: pd.DataFrame, horizon: int, name: str) -> np.ndarray:
    if name == "recent_7d_mean":
        daily = pd.to_numeric(frame["requested_avg_7"], errors="coerce").fillna(0.0)
    elif name == "recent_28d_mean":
        daily = pd.to_numeric(frame["requested_avg_28"], errors="coerce").fillna(0.0)
    elif name == "persistence":
        daily = pd.to_numeric(frame["requested_units"], errors="coerce").fillna(0.0)
    else:
        raise ValueError(f"unknown demand baseline: {name}")
    return np.maximum(daily.to_numpy(dtype=float) * float(horizon), 0.0)


def _demand_candidates() -> list[dict[str, object]]:
    return [
        {
            "loss": "squared_error",
            "learning_rate": 0.05,
            "max_iter": 220,
            "max_leaf_nodes": 31,
            "l2_regularization": 2.0,
        },
        {
            "loss": "poisson",
            "learning_rate": 0.05,
            "max_iter": 220,
            "max_leaf_nodes": 31,
            "l2_regularization": 2.0,
        },
        {
            "loss": "poisson",
            "learning_rate": 0.035,
            "max_iter": 280,
            "max_leaf_nodes": 63,
            "l2_regularization": 3.0,
        },
    ]


def _select_demand_blend(
    y_true: pd.Series | np.ndarray,
    baseline_prediction: np.ndarray,
    ml_prediction: np.ndarray,
    *,
    max_weight: float = 1.0,
) -> tuple[float, dict[str, float]]:
    """Choose a conservative validation-only ML weight with baseline fallback.

    The baseline is always an eligible production candidate. ML receives non-zero
    weight only when the validation blend improves both MAE and RMSE, preventing a
    strong naive forecast from being replaced merely to claim use of ML.
    """

    baseline_metrics = _regression_metrics(y_true, baseline_prediction)
    max_weight = float(np.clip(max_weight, 0.0, 1.0))
    best_weight = 0.0
    best_metrics = baseline_metrics
    best_score = 1.0
    candidate_weights = [
        weight
        for weight in (0.10, 0.20, 0.35, 0.50, 0.75, 1.00)
        if weight <= max_weight
    ]
    if 0.0 < max_weight < 1.0 and max_weight not in candidate_weights:
        candidate_weights.append(max_weight)
    for weight in sorted(candidate_weights):
        prediction = baseline_prediction + weight * (ml_prediction - baseline_prediction)
        prediction = np.maximum(prediction, 0.0)
        metrics = _regression_metrics(y_true, prediction)
        improves_mae = metrics["mae"] <= baseline_metrics["mae"] * 0.995
        improves_rmse = metrics["rmse"] <= baseline_metrics["rmse"] * 0.995
        if not (improves_mae and improves_rmse):
            continue
        score = 0.55 * metrics["mae"] / max(baseline_metrics["mae"], 1e-9) + 0.45 * (
            metrics["rmse"] / max(baseline_metrics["rmse"], 1e-9)
        )
        if score < best_score:
            best_score = score
            best_weight = float(weight)
            best_metrics = metrics
    return best_weight, best_metrics


def _rolling_origin_backtest(
    frame: pd.DataFrame,
    *,
    horizon: int,
    params: dict[str, object],
    baseline_name: str,
    blend_weight: float,
) -> dict[str, float]:
    dates = sorted(pd.to_datetime(frame["business_date"]).dt.date.unique())
    if len(dates) < 50:
        return {"folds": 0.0, "mean_mae_improvement_pct": -999.0, "mean_wape": 999.0}
    folds: list[dict[str, float]] = []
    for train_fraction in (0.55, 0.70):
        train_end = max(1, int(len(dates) * train_fraction))
        test_end = min(len(dates), train_end + max(4, int(len(dates) * 0.10)))
        safe_train_end = max(1, train_end - int(horizon))
        train_dates = set(dates[:safe_train_end])
        test_dates = set(dates[train_end:test_end])
        date_values = pd.to_datetime(frame["business_date"]).dt.date
        train = frame.loc[date_values.isin(train_dates)].copy()
        test = frame.loc[date_values.isin(test_dates)].copy()
        if len(train) < MIN_ACCEPTANCE_ROWS or len(test) < MIN_ACCEPTANCE_ROWS:
            continue
        if len(train) > 140_000:
            train = train.iloc[np.linspace(0, len(train) - 1, 140_000, dtype=int)]
        target = f"target_demand_{horizon}d"
        x_train = _clean_numeric(train, DEMAND_FEATURES)
        y_train = pd.to_numeric(train[target], errors="coerce").fillna(0.0)
        x_test = _clean_numeric(test, DEMAND_FEATURES)
        y_test = pd.to_numeric(test[target], errors="coerce").fillna(0.0)
        model = HistGradientBoostingRegressor(random_state=RANDOM_STATE, **params)
        model.fit(x_train, y_train)
        ml_prediction = np.maximum(model.predict(x_test), 0.0)
        baseline_prediction = _demand_baseline(test, horizon, baseline_name)
        prediction = np.maximum(
            baseline_prediction + blend_weight * (ml_prediction - baseline_prediction),
            0.0,
        )
        model_metrics = _regression_metrics(y_test, prediction)
        baseline_metrics = _regression_metrics(y_test, baseline_prediction)
        folds.append(
            {
                "wape": model_metrics["wape"],
                "mae_improvement_pct": 100.0
                * (baseline_metrics["mae"] - model_metrics["mae"])
                / max(baseline_metrics["mae"], 1e-9),
            }
        )
    if not folds:
        return {"folds": 0.0, "mean_mae_improvement_pct": -999.0, "mean_wape": 999.0}
    return {
        "folds": float(len(folds)),
        "mean_mae_improvement_pct": float(
            np.mean([row["mae_improvement_pct"] for row in folds])
        ),
        "mean_wape": float(np.mean([row["wape"] for row in folds])),
    }


def _train_demand(
    frame: pd.DataFrame, *, max_blend_weight: float = 1.0
) -> dict[str, object]:
    train, validation, test = _time_split_three(frame, embargo_days=max(DEMAND_HORIZONS))
    x_train = _clean_numeric(train, DEMAND_FEATURES)
    x_validation = _clean_numeric(validation, DEMAND_FEATURES)
    x_test = _clean_numeric(test, DEMAND_FEATURES)
    train_validation = pd.concat([train, validation], ignore_index=True)
    x_train_validation = _clean_numeric(train_validation, DEMAND_FEATURES)

    estimators: dict[int, HistGradientBoostingRegressor] = {}
    baseline_names_by_horizon: dict[int, str] = {}
    blend_weights: dict[int, float] = {}
    horizon_reports: dict[str, object] = {}
    flat_metrics: dict[str, float] = {}
    all_pass = True

    for horizon in DEMAND_HORIZONS:
        target = f"target_demand_{horizon}d"
        y_train = pd.to_numeric(train[target], errors="coerce").fillna(0.0)
        y_validation = pd.to_numeric(validation[target], errors="coerce").fillna(0.0)
        y_test = pd.to_numeric(test[target], errors="coerce").fillna(0.0)
        baseline_names = ("recent_7d_mean", "recent_28d_mean", "persistence")
        validation_baselines = {
            name: _regression_metrics(
                y_validation, _demand_baseline(validation, horizon, name)
            )
            for name in baseline_names
        }
        baseline_name = min(
            baseline_names,
            key=lambda name: (
                0.55 * validation_baselines[name]["mae"]
                + 0.45 * validation_baselines[name]["rmse"]
            ),
        )
        baseline_validation = validation_baselines[baseline_name]
        validation_baseline_prediction = _demand_baseline(
            validation, horizon, baseline_name
        )

        best_params: dict[str, object] | None = None
        best_score = math.inf
        best_validation_prediction: np.ndarray | None = None
        for params in _demand_candidates():
            candidate = HistGradientBoostingRegressor(random_state=RANDOM_STATE, **params)
            candidate.fit(x_train, y_train)
            pred = np.maximum(candidate.predict(x_validation), 0.0)
            metrics = _regression_metrics(y_validation, pred)
            score = 0.55 * metrics["mae"] / max(baseline_validation["mae"], 1e-9) + 0.45 * (
                metrics["rmse"] / max(baseline_validation["rmse"], 1e-9)
            )
            if score < best_score:
                best_score = score
                best_params = params
                best_validation_prediction = pred
        if best_params is None or best_validation_prediction is None:
            raise RuntimeError(f"demand model selection failed for horizon {horizon}")

        blend_weight, validation_blend_metrics = _select_demand_blend(
            y_validation,
            validation_baseline_prediction,
            best_validation_prediction,
            max_weight=max_blend_weight,
        )
        backtest = _rolling_origin_backtest(
            frame,
            horizon=horizon,
            params=best_params,
            baseline_name=baseline_name,
            blend_weight=blend_weight,
        )
        # A non-zero ML weight must also survive rolling-origin robustness checks
        # before it is allowed anywhere near the untouched final holdout.
        if blend_weight > 0.0 and backtest["mean_mae_improvement_pct"] <= 0.0:
            blend_weight = 0.0
            backtest = _rolling_origin_backtest(
                frame,
                horizon=horizon,
                params=best_params,
                baseline_name=baseline_name,
                blend_weight=0.0,
            )

        y_train_validation = pd.to_numeric(
            train_validation[target], errors="coerce"
        ).fillna(0.0)
        estimator = HistGradientBoostingRegressor(random_state=RANDOM_STATE, **best_params)
        estimator.fit(x_train_validation, y_train_validation)
        ml_prediction = np.maximum(estimator.predict(x_test), 0.0)
        baseline_prediction = _demand_baseline(test, horizon, baseline_name)
        prediction = np.maximum(
            baseline_prediction + blend_weight * (ml_prediction - baseline_prediction),
            0.0,
        )
        model_metrics = _regression_metrics(y_test, prediction)
        baseline_metrics = _regression_metrics(y_test, baseline_prediction)
        paired_ci = _paired_mae_improvement_ci(y_test, prediction, baseline_prediction)
        segment_metrics = _demand_segment_metrics(test, y_test, prediction)
        mae_improvement = 100.0 * (baseline_metrics["mae"] - model_metrics["mae"]) / max(
            baseline_metrics["mae"], 1e-9
        )
        rmse_improvement = 100.0 * (
            baseline_metrics["rmse"] - model_metrics["rmse"]
        ) / max(baseline_metrics["rmse"], 1e-9)
        minimum_r2 = 0.50 if horizon == 1 else 0.60
        mae_noninferiority_margin = 0.01 * baseline_metrics["mae"]
        horizon_pass = (
            model_metrics["r2"] >= minimum_r2
            and model_metrics["wape"] <= 0.45
            and model_metrics["mae"] <= baseline_metrics["mae"] * 1.01
            and model_metrics["rmse"] <= baseline_metrics["rmse"] * 1.02
            and paired_ci["ci95_low"] >= -mae_noninferiority_margin
            and backtest["folds"] >= 2
            and backtest["mean_mae_improvement_pct"] >= -1.0
        )
        all_pass = all_pass and horizon_pass
        estimators[horizon] = estimator
        baseline_names_by_horizon[horizon] = baseline_name
        blend_weights[horizon] = blend_weight
        deployment_mode = "hybrid_ml" if blend_weight > 0.0 else "baseline_safety_fallback"
        horizon_reports[str(horizon)] = {
            "gate": "PASS" if horizon_pass else "FAIL",
            "deployment_mode": deployment_mode,
            "baseline": baseline_name,
            "ml_blend_weight": blend_weight,
            "metrics": model_metrics,
            "baseline_metrics": baseline_metrics,
            "validation_blend_metrics": validation_blend_metrics,
            "mae_improvement_pct": mae_improvement,
            "rmse_improvement_pct": rmse_improvement,
            "rolling_origin": backtest,
            "paired_mae_improvement_ci95": paired_ci,
            "demand_volume_quartiles": segment_metrics,
            "params": best_params,
        }
        for name, value in model_metrics.items():
            flat_metrics[f"h{horizon}_{name}"] = value
        flat_metrics[f"h{horizon}_mae_improvement_pct"] = mae_improvement
        flat_metrics[f"h{horizon}_rmse_improvement_pct"] = rmse_improvement
        flat_metrics[f"h{horizon}_backtest_wape"] = backtest["mean_wape"]
        flat_metrics[f"h{horizon}_ml_blend_weight"] = blend_weight

    model = MultiHorizonDemandModel(
        estimators=estimators,
        feature_names=DEMAND_FEATURES,
        baseline_names=baseline_names_by_horizon,
        blend_weights=blend_weights,
    )
    quality = {
        "gate": "PASS" if all_pass else "FAIL",
        "production_ready": all_pass,
        "validation": (
            "temporal_holdout + rolling_origin + multiple_naive_baselines + "
            "validation_only_conservative_blending"
        ),
        "horizons_days": list(DEMAND_HORIZONS),
        "all_horizons_must_pass": True,
        "target_leakage": False,
        "forecast_cutoff": "end_of_business_day",
        "baseline_safety_fallback_allowed": True,
        "ml_is_never_forced_when_baseline_is_stronger": True,
        "synthetic_backfill_tail_risk_guard": max_blend_weight < 1.0,
        "max_ml_blend_weight": max_blend_weight,
    }
    return _register_candidate(
        model=model,
        spec_key="demand_forecast",
        features=DEMAND_FEATURES,
        metrics=flat_metrics,
        params={
            "algorithm": "ConservativeHybridDemandForecast",
            "base_estimator": "HistGradientBoostingRegressor_per_horizon",
            "horizons": DEMAND_HORIZONS,
            "blend_weights": blend_weights,
        },
        quality=quality,
        x_example=x_train_validation.head(10),
        training_rows=len(train_validation),
        test_rows=len(test),
        extra_metadata={
            "output_names": model.output_names_,
            "horizon_reports": horizon_reports,
            "baseline_names": baseline_names_by_horizon,
            "blend_weights": blend_weights,
        },
    )


def _expected_calibration_error(
    y_true: np.ndarray, probability: np.ndarray, bins: int = 10
) -> float:
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = max(len(y_true), 1)
    error_value = 0.0
    for index in range(bins):
        low, high = edges[index], edges[index + 1]
        if index == bins - 1:
            mask = (probability >= low) & (probability <= high)
        else:
            mask = (probability >= low) & (probability < high)
        if not np.any(mask):
            continue
        error_value += float(np.sum(mask)) / total * abs(
            float(np.mean(probability[mask])) - float(np.mean(y_true[mask]))
        )
    return float(error_value)


def _rare_event_requirements(prevalence: float) -> dict[str, float]:
    """Scale ranking/lift requirements to the observed event prevalence.

    Lift is the meaningful quantity for rare events; an absolute precision target
    becomes nonsensical when prevalence changes by orders of magnitude.
    """

    if prevalence < 0.005:
        return {
            "pr_auc_lift": 10.0,
            "precision_lift": 5.0,
            "top10_recall": 0.50,
            "top10_lift": 3.0,
        }
    if prevalence < 0.02:
        return {
            "pr_auc_lift": 5.0,
            "precision_lift": 3.0,
            "top10_recall": 0.40,
            "top10_lift": 2.0,
        }
    return {
        "pr_auc_lift": 2.0,
        "precision_lift": 1.5,
        "top10_recall": 0.30,
        "top10_lift": 1.5,
    }


def _choose_threshold(
    y_true: np.ndarray, probability: np.ndarray
) -> tuple[float, dict[str, float]]:
    """Select a rare-event operating threshold using validation data only.

    Fixed thresholds such as 0.5 are inappropriate when a calibrated event has
    sub-1% prevalence. The selector therefore searches the precision-recall curve
    and enforces recall, lift, and alert-budget constraints.
    """

    y = np.asarray(y_true, dtype=int)
    prob = np.clip(np.asarray(probability, dtype=float), 0.0, 1.0)
    prevalence = max(float(np.mean(y)), 1e-9)
    requirements = _rare_event_requirements(prevalence)
    precision, recall, thresholds = precision_recall_curve(y, prob)
    best: tuple[float, float, float, float, float] | None = None
    for index, threshold in enumerate(thresholds):
        precision_value = float(precision[index])
        recall_value = float(recall[index])
        prediction = prob >= float(threshold)
        alert_rate = float(np.mean(prediction))
        precision_lift = precision_value / prevalence
        if (
            recall_value < 0.50
            or precision_lift < requirements["precision_lift"]
            or alert_rate > 0.10
        ):
            continue
        beta2 = 4.0
        denominator = beta2 * precision_value + recall_value
        f2 = (1.0 + beta2) * precision_value * recall_value / max(denominator, 1e-12)
        candidate = (f2, precision_lift, -alert_rate, float(threshold), recall_value)
        if best is None or candidate[:3] > best[:3]:
            best = candidate

    if best is None:
        # Capacity-safe fallback: alert roughly the highest-risk decile. This remains
        # validation-only and is substantially more appropriate than threshold=0.5.
        threshold = float(np.quantile(prob, 0.90))
        prediction = prob >= threshold
        precision_value = float(precision_score(y, prediction, zero_division=0))
        recall_value = float(recall_score(y, prediction, zero_division=0))
        alert_rate = float(np.mean(prediction))
        return threshold, {
            "selection": "validation_top10pct_fallback",
            "validation_precision": precision_value,
            "validation_recall": recall_value,
            "validation_alert_rate": alert_rate,
            "validation_precision_lift": precision_value / prevalence,
        }

    _, precision_lift, negative_alert_rate, threshold, recall_value = best
    prediction = prob >= threshold
    precision_value = float(precision_score(y, prediction, zero_division=0))
    return threshold, {
        "selection": "validation_precision_recall_operating_point",
        "validation_precision": precision_value,
        "validation_recall": float(recall_value),
        "validation_alert_rate": float(-negative_alert_rate),
        "validation_precision_lift": float(precision_lift),
    }


def _binary_metrics(
    y_true: np.ndarray, probability: np.ndarray, threshold: float
) -> dict[str, float]:
    prediction = probability >= threshold
    prevalence = float(np.mean(y_true))
    top_count = max(1, int(len(probability) * 0.10))
    top_index = np.argsort(probability)[-top_count:]
    positives = max(int(np.sum(y_true)), 1)
    top_positives = int(np.sum(y_true[top_index]))
    precision_top10 = float(top_positives / top_count)
    true_negative = int(np.sum((y_true == 0) & (~prediction)))
    false_positive = int(np.sum((y_true == 0) & prediction))
    specificity = float(true_negative / max(true_negative + false_positive, 1))
    recall_value = float(recall_score(y_true, prediction, zero_division=0))
    return {
        "prevalence": prevalence,
        "average_precision": float(average_precision_score(y_true, probability)),
        "pr_auc_lift_vs_prevalence": float(
            average_precision_score(y_true, probability) / max(prevalence, 1e-9)
        ),
        "roc_auc": float(roc_auc_score(y_true, probability)),
        "brier": float(brier_score_loss(y_true, probability)),
        "ece_10bin": _expected_calibration_error(y_true, probability),
        "precision": float(precision_score(y_true, prediction, zero_division=0)),
        "precision_lift_vs_prevalence": float(
            precision_score(y_true, prediction, zero_division=0) / max(prevalence, 1e-9)
        ),
        "recall": recall_value,
        "alert_rate": float(np.mean(prediction)),
        "specificity": specificity,
        "balanced_accuracy": float((recall_value + specificity) / 2.0),
        "f1": float(f1_score(y_true, prediction, zero_division=0)),
        "f2": float(fbeta_score(y_true, prediction, beta=2, zero_division=0)),
        "threshold": float(threshold),
        "precision_at_top10pct": precision_top10,
        "recall_at_top10pct": float(top_positives / positives),
        "lift_at_top10pct": float(precision_top10 / max(prevalence, 1e-9)),
    }


def _train_stockout(frame: pd.DataFrame) -> dict[str, object]:
    train, validation, test = _time_split_three(frame, embargo_days=7)
    x_train = _clean_numeric(train, STOCKOUT_FEATURES)
    x_validation = _clean_numeric(validation, STOCKOUT_FEATURES)
    x_test = _clean_numeric(test, STOCKOUT_FEATURES)
    y_train = pd.to_numeric(train["target_stockout_7d"], errors="coerce").fillna(0).astype(int)
    y_validation = (
        pd.to_numeric(validation["target_stockout_7d"], errors="coerce").fillna(0).astype(int)
    )
    y_test = pd.to_numeric(test["target_stockout_7d"], errors="coerce").fillna(0).astype(int)
    positive_counts = {
        "train": int(y_train.sum()),
        "validation": int(y_validation.sum()),
        "test": int(y_test.sum()),
    }
    prevalence = {
        "train": float(y_train.mean()),
        "validation": float(y_validation.mean()),
        "test": float(y_test.mean()),
    }
    print(
        "Stockout label diagnostics: "
        f"positives={positive_counts} prevalence={prevalence}"
    )
    total_positives = int(sum(positive_counts.values()))
    sufficiency_failures: list[str] = []
    if positive_counts["train"] < MIN_TRAIN_POSITIVES:
        sufficiency_failures.append(
            f"train<{MIN_TRAIN_POSITIVES}"
        )
    if positive_counts["validation"] < MIN_VALIDATION_POSITIVES:
        sufficiency_failures.append(
            f"validation<{MIN_VALIDATION_POSITIVES}"
        )
    if positive_counts["test"] < MIN_TEST_POSITIVES:
        sufficiency_failures.append(
            f"test<{MIN_TEST_POSITIVES}"
        )
    if total_positives < MIN_TOTAL_POSITIVES:
        sufficiency_failures.append(
            f"total<{MIN_TOTAL_POSITIVES}"
        )
    if sufficiency_failures:
        raise RuntimeError(
            "stockout scientific validation has insufficient rare-event support after "
            f"leakage-safe simulation: positives={positive_counts}; "
            f"total_positives={total_positives}; failures={sufficiency_failures}"
        )
    print(
        "Stockout rare-event sufficiency: PASS "
        f"(train>={MIN_TRAIN_POSITIVES}, validation>={MIN_VALIDATION_POSITIVES}, "
        f"test>={MIN_TEST_POSITIVES}, total>={MIN_TOTAL_POSITIVES})"
    )

    candidates = [
        {"learning_rate": 0.05, "max_iter": 180, "max_leaf_nodes": 31, "l2_regularization": 1.0},
        {"learning_rate": 0.08, "max_iter": 160, "max_leaf_nodes": 31, "l2_regularization": 2.0},
        {"learning_rate": 0.04, "max_iter": 240, "max_leaf_nodes": 63, "l2_regularization": 3.0},
    ]
    best_params: dict[str, object] | None = None
    best_ap = -1.0
    best_estimator: HistGradientBoostingClassifier | None = None
    for params in candidates:
        estimator = HistGradientBoostingClassifier(
            random_state=RANDOM_STATE,
            class_weight="balanced",
            **params,
        )
        estimator.fit(x_train, y_train)
        probability = estimator.predict_proba(x_validation)[:, 1]
        ap = float(average_precision_score(y_validation, probability))
        if ap > best_ap:
            best_ap = ap
            best_params = params
            best_estimator = estimator
    if best_estimator is None or best_params is None:
        raise RuntimeError("stockout classifier selection produced no candidate")

    raw_validation = np.clip(best_estimator.predict_proba(x_validation)[:, 1], 1e-6, 1 - 1e-6)
    validation_logits = np.log(raw_validation / (1.0 - raw_validation)).reshape(-1, 1)
    calibrator = LogisticRegression(random_state=RANDOM_STATE, max_iter=300)
    calibrator.fit(validation_logits, y_validation)
    calibrated_validation = calibrator.predict_proba(validation_logits)[:, 1]
    threshold, threshold_diagnostics = _choose_threshold(
        y_validation.to_numpy(dtype=int), calibrated_validation
    )
    model = CalibratedThresholdClassifier(
        estimator=best_estimator,
        calibrator=calibrator,
        threshold=threshold,
        feature_names=STOCKOUT_FEATURES,
    )
    test_probability = model.predict_proba(x_test)[:, 1]
    metrics = _binary_metrics(y_test.to_numpy(dtype=int), test_probability, threshold)
    train_prevalence = float(np.mean(y_train.to_numpy(dtype=float)))
    baseline_brier = float(
        brier_score_loss(
            y_test.to_numpy(dtype=int),
            np.full(len(y_test), train_prevalence, dtype=float),
        )
    )
    rare_requirements = _rare_event_requirements(metrics["prevalence"])
    gate_pass = (
        len(test) >= MIN_ACCEPTANCE_ROWS
        and metrics["pr_auc_lift_vs_prevalence"] >= rare_requirements["pr_auc_lift"]
        and metrics["roc_auc"] >= 0.75
        and metrics["brier"] < baseline_brier
        and metrics["ece_10bin"] <= 0.05
        and metrics["recall_at_top10pct"] >= rare_requirements["top10_recall"]
        and metrics["lift_at_top10pct"] >= rare_requirements["top10_lift"]
        and metrics["recall"] >= 0.30
        and metrics["precision_lift_vs_prevalence"] >= rare_requirements["precision_lift"]
        and metrics["alert_rate"] <= 0.15
    )
    metrics.update(
        {
            "baseline_brier": baseline_brier,
            "validation_average_precision": best_ap,
            "validation_threshold_recall": float(
                threshold_diagnostics["validation_recall"]
            ),
            "validation_threshold_precision_lift": float(
                threshold_diagnostics["validation_precision_lift"]
            ),
            "validation_threshold_alert_rate": float(
                threshold_diagnostics["validation_alert_rate"]
            ),
        }
    )
    quality = {
        "gate": "PASS" if gate_pass else "FAIL",
        "production_ready": gate_pass,
        "validation": (
            "future_7d_label + temporal_holdout + Platt_calibration + "
            "validation_only_rare_event_threshold"
        ),
        "class_imbalance": "balanced_training",
        "minimum_roc_auc": 0.75,
        "minimum_recall": 0.30,
        "prevalence_scaled_requirements": rare_requirements,
        "rare_event_sufficiency": {
            "train_positive_min": MIN_TRAIN_POSITIVES,
            "validation_positive_min": MIN_VALIDATION_POSITIVES,
            "test_positive_min": MIN_TEST_POSITIVES,
            "total_positive_min": MIN_TOTAL_POSITIVES,
            "observed_positive_counts": positive_counts,
            "observed_total_positives": total_positives,
        },
        "must_beat_constant_probability_brier": True,
        "target_leakage": False,
        "operating_threshold_selection": threshold_diagnostics,
        "primary_rare_event_metrics": [
            "PR-AUC lift vs prevalence",
            "ROC-AUC",
            "Brier score",
            "calibration error",
            "Recall@Top10%",
            "Lift@Top10%",
        ],
    }
    return _register_candidate(
        model=model,
        spec_key="stockout_risk",
        features=STOCKOUT_FEATURES,
        metrics=metrics,
        params={
            "algorithm": "HistGradientBoostingClassifier+PlattCalibration",
            "target_horizon_days": 7,
            "decision_threshold": threshold,
            **best_params,
        },
        quality=quality,
        x_example=x_train.head(10),
        training_rows=len(train),
        test_rows=len(test),
    )


def _reorder_scenario_gate(model: ReorderPolicyModel) -> bool:
    low_supply = pd.DataFrame(
        [{
            "available_units": 2.0,
            "avg_daily_requested_units": 10.0,
            "demand_stddev_units": 3.0,
            "supplier_lead_time_days": 4.0,
            "supplier_reliability": 0.90,
            "inbound_units": 0.0,
        }]
    )
    high_supply = low_supply.copy()
    high_supply.loc[0, "available_units"] = 250.0
    low = float(model.predict(low_supply)[0])
    high = float(model.predict(high_supply)[0])
    return low > high and low > 0.0 and high == 0.0


def _train_reorder(history: pd.DataFrame) -> dict[str, object]:
    replay = history.copy()
    replay["avg_daily_requested_units"] = pd.to_numeric(
        replay["requested_avg_28"], errors="coerce"
    ).fillna(0.0)
    replay["demand_stddev_units"] = pd.to_numeric(
        replay["requested_stddev_28"], errors="coerce"
    ).fillna(0.0)
    if "inbound_units" not in replay.columns:
        replay["inbound_units"] = 0.0
    else:
        replay["inbound_units"] = pd.to_numeric(
            replay["inbound_units"], errors="coerce"
        ).fillna(0.0)
    x = _clean_numeric(replay, REORDER_FEATURES)
    model = ReorderPolicyModel(review_period_days=7.0, service_z=1.65).fit(x)
    recommendation = model.predict(x)
    reliability = np.clip(x["supplier_reliability"].to_numpy(), 0.50, 1.0)
    lead_days = np.maximum(x["supplier_lead_time_days"].to_numpy(), 1.0) / reliability
    protection_days = lead_days + 7.0
    future_7 = pd.to_numeric(replay["future_demand_7d"], errors="coerce").fillna(0.0).to_numpy()
    future_14 = pd.to_numeric(replay["future_demand_14d"], errors="coerce").fillna(0.0).to_numpy()
    future_21 = pd.to_numeric(replay["future_demand_21d"], errors="coerce").fillna(0.0).to_numpy()
    realized = np.where(
        protection_days <= 7,
        future_7,
        np.where(protection_days <= 14, future_14, future_21),
    )
    available = np.maximum(x["available_units"].to_numpy(), 0.0)
    inbound = np.maximum(x["inbound_units"].to_numpy(), 0.0) * reliability
    mean_daily = np.maximum(x["avg_daily_requested_units"].to_numpy(), 0.0)
    baseline_order = np.ceil(np.maximum(mean_daily * protection_days - available - inbound, 0.0))
    policy_supply = available + inbound + recommendation
    baseline_supply = available + inbound + baseline_order
    policy_lost = np.maximum(realized - policy_supply, 0.0)
    baseline_lost = np.maximum(realized - baseline_supply, 0.0)
    policy_over = np.maximum(policy_supply - realized, 0.0)
    baseline_over = np.maximum(baseline_supply - realized, 0.0)
    policy_fill = 1.0 - float(np.sum(policy_lost) / max(np.sum(realized), 1.0))
    baseline_fill = 1.0 - float(np.sum(baseline_lost) / max(np.sum(realized), 1.0))
    scenario_pass = _reorder_scenario_gate(model)
    metrics = {
        "historical_replay_fill_rate": policy_fill,
        "baseline_fill_rate": baseline_fill,
        "lost_units": float(np.sum(policy_lost)),
        "baseline_lost_units": float(np.sum(baseline_lost)),
        "mean_overstock_units": float(np.mean(policy_over)),
        "baseline_mean_overstock_units": float(np.mean(baseline_over)),
        "recommendation_mean_units": float(np.mean(recommendation)),
        "baseline_order_mean_units": float(np.mean(baseline_order)),
        "positive_recommendation_rate": float(np.mean(recommendation > 0.0)),
        "scenario_gate": float(scenario_pass),
    }
    overstock_limit = metrics["baseline_mean_overstock_units"] * 1.60 + 2.0
    gate_pass = (
        len(x) >= MIN_ACCEPTANCE_ROWS
        and scenario_pass
        and policy_fill >= baseline_fill
        and metrics["lost_units"] <= metrics["baseline_lost_units"]
        and metrics["mean_overstock_units"] <= overstock_limit
        and 0.01 <= metrics["positive_recommendation_rate"] <= 0.95
    )
    quality = {
        "gate": "PASS" if gate_pass else "FAIL",
        "production_ready": gate_pass,
        "validation": "historical future-demand replay + service-level invariant scenarios",
        "target_leakage": False,
        "decision_type": "prescriptive_inventory_optimization",
        "must_not_worsen_lost_sales": True,
        "overstock_guard": overstock_limit,
    }
    return _register_candidate(
        model=model,
        spec_key="reorder_recommendation",
        features=REORDER_FEATURES,
        metrics=metrics,
        params={
            "algorithm": "order_up_to_service_level_policy",
            "review_period_days": 7.0,
            "service_z": 1.65,
            "supplier_reliability_adjusted": True,
        },
        quality=quality,
        x_example=x.head(10),
        training_rows=len(x),
        test_rows=len(x),
    )


def _expiry_scenario_gate(model: ExpiryRiskModel) -> bool:
    risky = pd.DataFrame(
        [{
            "days_to_expiry": 20.0,
            "quantity_on_hand": 100.0,
            "avg_daily_units_sold": 0.5,
            "demand_stddev_units": 0.8,
        }]
    )
    safe = pd.DataFrame(
        [{
            "days_to_expiry": 365.0,
            "quantity_on_hand": 20.0,
            "avg_daily_units_sold": 5.0,
            "demand_stddev_units": 2.0,
        }]
    )
    near = float(model.predict_proba(risky)[0, 1])
    far = float(model.predict_proba(safe)[0, 1])
    return near > 0.80 and far < 0.20 and near > far


def _simulate_total_demand(
    rng: np.random.Generator, mean_total: float, variance_total: float, size: int
) -> np.ndarray:
    if mean_total <= 0.0:
        return np.zeros(size, dtype=float)
    variance_total = max(float(variance_total), mean_total)
    if variance_total <= mean_total * 1.01:
        return rng.poisson(mean_total, size=size).astype(float)
    n = mean_total**2 / max(variance_total - mean_total, 1e-9)
    p = n / (n + mean_total)
    return rng.negative_binomial(n, p, size=size).astype(float)


def _expiry_stochastic_calibration(model: ExpiryRiskModel) -> dict[str, object]:
    scenarios = [
        (14.0, 60.0, 2.0, 2.5),
        (30.0, 100.0, 2.5, 3.0),
        (60.0, 80.0, 1.5, 2.0),
        (90.0, 120.0, 1.0, 1.8),
        (180.0, 40.0, 2.0, 2.2),
        (365.0, 20.0, 5.0, 3.0),
    ]
    rng = np.random.default_rng(RANDOM_STATE)
    errors: list[float] = []
    predicted_values: list[float] = []
    empirical_values: list[float] = []
    rows: list[dict[str, float]] = []
    for days, on_hand, velocity, sigma in scenarios:
        frame = pd.DataFrame(
            [{
                "days_to_expiry": days,
                "quantity_on_hand": on_hand,
                "avg_daily_units_sold": velocity,
                "demand_stddev_units": sigma,
            }]
        )
        predicted = float(model.predict_proba(frame)[0, 1])
        mean_total = velocity * days
        variance_total = sigma**2 * days
        simulated = _simulate_total_demand(rng, mean_total, variance_total, 8_000)
        empirical = float(np.mean(simulated < on_hand))
        error_value = abs(predicted - empirical)
        predicted_values.append(predicted)
        empirical_values.append(empirical)
        errors.append(error_value)
        rows.append(
            {
                "days_to_expiry": days,
                "on_hand": on_hand,
                "predicted_risk": predicted,
                "empirical_risk": empirical,
                "absolute_error": error_value,
            }
        )
    correlation = float(np.corrcoef(predicted_values, empirical_values)[0, 1])
    return {
        "calibration_mae": float(np.mean(errors)),
        "calibration_max_error": float(np.max(errors)),
        "rank_correlation": correlation,
        "scenarios": rows,
    }


def _train_expiry(frame: pd.DataFrame) -> dict[str, object]:
    x = _clean_numeric(frame, EXPIRY_FEATURES)
    model = ExpiryRiskModel(threshold=0.50).fit(x)
    probability = model.predict_proba(x)[:, 1]
    finite = bool(np.isfinite(probability).all())
    bounded = bool(((probability >= 0.0) & (probability <= 1.0)).all())
    scenario_pass = _expiry_scenario_gate(model)
    calibration = _expiry_stochastic_calibration(model)
    days = pd.to_numeric(frame["days_to_expiry"], errors="coerce").fillna(0.0).to_numpy()
    near_expiry_rows = int(np.sum((days >= 0) & (days <= 90)))
    expired_rows = int(np.sum(days <= 0))
    gate_pass = (
        len(x) >= MIN_ACCEPTANCE_ROWS
        and finite
        and bounded
        and scenario_pass
        and float(calibration["calibration_mae"]) <= 0.15
        and float(calibration["rank_correlation"]) >= 0.90
    )
    metrics = {
        "risk_mean": float(np.mean(probability)),
        "risk_p95": float(np.quantile(probability, 0.95)),
        "high_risk_rate": float(np.mean(probability >= 0.50)),
        "near_expiry_rows": float(near_expiry_rows),
        "expired_rows": float(expired_rows),
        "scenario_gate": float(scenario_pass),
        "stochastic_calibration_mae": float(calibration["calibration_mae"]),
        "stochastic_calibration_max_error": float(calibration["calibration_max_error"]),
        "stochastic_rank_correlation": float(calibration["rank_correlation"]),
    }
    quality = {
        "gate": "PASS" if gate_pass else "FAIL",
        "production_ready": gate_pass,
        "validation": "count-demand stochastic calibration + monotonic stress scenarios",
        "supervised_label_used": False,
        "as_of_date": "dataset_max_business_date",
        "right_censoring_disclosed": True,
        "observed_expiry_outcomes_available": expired_rows > 0,
        "note": (
            "Stage 7E creates long-dated active batches, so observed expiry-loss labels are "
            "right-censored. The production engine is therefore validated as a calibrated "
            "sell-through probability model rather than using fabricated labels."
        ),
    }
    return _register_candidate(
        model=model,
        spec_key="expiry_slow_moving_risk",
        features=EXPIRY_FEATURES,
        metrics=metrics,
        params={
            "algorithm": "aggregate_demand_probability_normal_approximation",
            "calibration_reference": "negative_binomial_or_poisson_count_simulation",
            "decision_threshold": 0.50,
        },
        quality=quality,
        x_example=x.head(10),
        training_rows=len(x),
        test_rows=len(x),
        extra_metadata={"stochastic_calibration": calibration},
    )


def _write_model_cards(results: list[dict[str, object]]) -> None:
    cards_dir = STAGE7K_ROOT / "model_cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    for result in results:
        card = {
            "stage": "7K",
            "hardening": f"v{STAGE7K_VERSION}",
            "generated_at": datetime.now(UTC).isoformat(),
            **result,
        }
        (cards_dir / f"{result['model_key']}.json").write_text(
            json.dumps(_json_safe(card), indent=2, sort_keys=True), encoding="utf-8"
        )


def main() -> None:
    config = config_from_environment()
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000"))
    mlflow.set_experiment(EXPERIMENT_NAME)

    client = bigquery.Client(project=config.project_id)
    max_bytes = int(config.max_query_gib * 1024**3)
    print(
        "=== PharmStock Stage 7K / Scientific Validation + "
        f"Backtesting v{STAGE7K_VERSION} ==="
    )
    print(f"Project:               {config.project_id}")
    print("BigQuery mode:         READ ONLY")
    print(f"Gold dataset:          {config.gold_dataset}")
    print(f"Current-state dataset: {config.current_dataset}")
    print(f"Max rows/query:        {config.max_training_rows:,}")
    print("Champion policy:       STRICT / all scientific gates must PASS")

    coverage = _query_dataframe(client, history_coverage_sql(config), max_bytes)
    if coverage.empty:
        raise RuntimeError("Stage 7K could not determine historical coverage")
    coverage_row = coverage.iloc[0]
    observed_days = int(coverage_row.get("gold_distinct_days") or 0)
    gold_max_date = pd.to_datetime(coverage_row.get("gold_max_date"), errors="coerce")
    if pd.isna(gold_max_date):
        raise RuntimeError("Stage 7K historical coverage has no valid max business date")
    end_date = gold_max_date.date()
    print(f"Observed Gold history: {observed_days:,} distinct days")
    print(f"Minimum for 30d ML:    {MIN_OBSERVED_HISTORY_DAYS:,} days")

    if observed_days >= MIN_OBSERVED_HISTORY_DAYS:
        temporal = _query_dataframe(client, product_temporal_feature_sql(config), max_bytes)
        stockout_history = _query_dataframe(
            client, stockout_supervised_feature_sql(config), max_bytes
        )
        history_provenance = "OBSERVED_WAREHOUSE_HISTORY"
        print("Offline ML backfill:    NOT REQUIRED")
    else:
        print(
            "Offline ML backfill:    REQUIRED / zero-cost local synthetic-calibrated "
            f"{DEFAULT_OFFLINE_HISTORY_DAYS}d history"
        )
        demand_seed = _query_dataframe(client, demand_calibration_seed_sql(config), max_bytes)
        stockout_seed = _query_dataframe(client, stockout_calibration_seed_sql(config), max_bytes)
        temporal = build_demand_history(
            demand_seed,
            end_date=end_date,
            days=DEFAULT_OFFLINE_HISTORY_DAYS,
            row_budget=config.max_training_rows,
        )
        stockout_history = build_stockout_history(
            stockout_seed,
            end_date=end_date,
            days=DEFAULT_OFFLINE_HISTORY_DAYS,
            row_budget=config.max_training_rows,
        )
        persist_offline_history(
            temporal,
            stockout_history,
            root=STAGE7K_ROOT / "offline_training_store",
            observed_history_days=observed_days,
            generated_history_days=DEFAULT_OFFLINE_HISTORY_DAYS,
        )
        history_provenance = OFFLINE_HISTORY_PROVENANCE

    expiry = _query_dataframe(client, expiry_feature_sql(config), max_bytes)
    print(f"Training provenance:   {history_provenance}")
    print(f"Demand history rows:   {len(temporal):,}")
    print(f"Stockout history rows: {len(stockout_history):,}")
    print(f"Expiry feature rows:   {len(expiry):,}")
    demand_max_blend_weight = (
        SYNTHETIC_BACKFILL_MAX_BLEND_WEIGHT
        if history_provenance == OFFLINE_HISTORY_PROVENANCE
        else 1.0
    )
    print(f"Demand ML blend cap:    {demand_max_blend_weight:.2f}")
    if min(len(temporal), len(stockout_history), len(expiry)) < MIN_ACCEPTANCE_ROWS:
        raise RuntimeError(
            "Stage 7K scientific feature extraction/backfill returned fewer than 1,000 rows"
        )

    results = [
        _train_demand(temporal, max_blend_weight=demand_max_blend_weight),
        _train_stockout(stockout_history),
        _train_reorder(stockout_history),
        _train_expiry(expiry),
    ]
    provenance_client = MlflowClient()
    for result in results:
        result["training_data_provenance"] = (
            history_provenance
            if result["model_key"] in {"demand_forecast", "stockout_risk", "reorder_recommendation"}
            else "OBSERVED_CURRENT_STATE_PLUS_STOCHASTIC_CALIBRATION"
        )
        result["observed_history_days"] = observed_days
        provenance_client.set_model_version_tag(
            str(result["registered_name"]),
            str(result["version"]),
            "training_data_provenance",
            str(result["training_data_provenance"]),
        )
        provenance_client.set_model_version_tag(
            str(result["registered_name"]),
            str(result["version"]),
            "observed_history_days",
            str(observed_days),
        )
    _write_model_cards(results)

    print("Scientific candidate gates:")
    for result in results:
        print(
            f"  {result['model_key']:<28} version={result['version']} "
            f"gate={result['quality']['gate']} "
            f"metrics={json.dumps(result['metrics'], sort_keys=True)}"
        )
    _promote_all(results)

    models_dir = STAGE7K_ROOT / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    mlflow_client = MlflowClient()
    for result in results:
        key = str(result["model_key"])
        name = str(result["registered_name"])
        model = mlflow.sklearn.load_model(f"models:/{name}@champion")
        joblib.dump(model, models_dir / f"{key}.joblib", compress=3)
        alias = mlflow_client.get_model_version_by_alias(name, "champion")
        result["version"] = str(alias.version)
        result["alias"] = "champion"

    manifest = {
        "stage": "7K",
        "hardening": f"v{STAGE7K_VERSION}",
        "generated_at": datetime.now(UTC).isoformat(),
        "project_id": config.project_id,
        "bigquery_writes": False,
        "feature_tables_created": False,
        "strict_champion_gate": True,
        "scientific_validation": True,
        "training_data_provenance": history_provenance,
        "observed_history_days": observed_days,
        "production_ready_models": sum(bool(item["production_ready"]) for item in results),
        "mlflow_tracking_uri": os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000"),
        "models": results,
    }
    STAGE7K_ROOT.mkdir(parents=True, exist_ok=True)
    (STAGE7K_ROOT / "training_manifest.json").write_text(
        json.dumps(_json_safe(manifest), indent=2, sort_keys=True), encoding="utf-8"
    )
    (STAGE7K_ROOT / "_SCIENTIFIC_VALIDATION_PASS").write_text(
        manifest["generated_at"] + "\n", encoding="utf-8"
    )
    (STAGE7K_ROOT / "_TRAINED").write_text(manifest["generated_at"] + "\n", encoding="utf-8")
    print("Registered scientific production champions: 4/4")
    print("STAGE_7K_SCIENTIFIC_VALIDATION_STATUS=PASS")
    print("STAGE_7K_MODEL_QUALITY_STATUS=PASS")
    print("STAGE_7K_TRAINING_STATUS=PASS")


if __name__ == "__main__":
    main()
