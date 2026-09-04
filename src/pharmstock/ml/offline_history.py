"""Zero-cost offline ML history extension for Stage 7K.

The operational BigQuery baseline is intentionally storage-constrained in Sandbox.
When that observed window is too short for 28-day lags and 30-day forecast targets,
this module creates an explicitly SYNTHETIC_CALIBRATED offline training store from
observed aggregates. It never writes to BigQuery and never pretends the backfilled
period is observed production history.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

OFFLINE_HISTORY_PROVENANCE = "SYNTHETIC_CALIBRATED_OFFLINE_BACKFILL"
DEFAULT_OFFLINE_HISTORY_DAYS = 365
MIN_OBSERVED_HISTORY_DAYS = 90


@dataclass(frozen=True, slots=True)
class OfflineHistorySummary:
    observed_history_days: int
    generated_history_days: int
    demand_rows: int
    stockout_rows: int
    provenance: str = OFFLINE_HISTORY_PROVENANCE


def _stable_unit_interval(value: object, salt: str) -> float:
    payload = f"{salt}|{value}".encode()
    digest = hashlib.sha256(payload).digest()
    integer = int.from_bytes(digest[:8], "big", signed=False)
    return integer / float(2**64 - 1)


def _rng_for(value: object, salt: str) -> np.random.Generator:
    payload = f"{salt}|{value}".encode()
    seed = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
    return np.random.default_rng(seed)


def _sample_count(row_budget: int, usable_days: int, seed_rows: int) -> int:
    if seed_rows <= 0:
        return 0
    return max(1, min(seed_rows, row_budget // max(usable_days, 1)))


def _finite_float(value: object, default: float = 0.0) -> float:
    """Coerce nullable/NaN calibration values to a finite deterministic default.

    BigQuery aggregate functions such as STDDEV_SAMP legitimately return NULL for
    one-observation groups. Pandas represents those NULLs as NaN, and ``NaN or x``
    does not fall back to ``x`` because NaN is truthy. Keeping this guard at the
    offline-history boundary prevents non-finite values from entering inventory
    arithmetic, random count distributions, or integer order quantities.
    """

    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if math.isfinite(number) else float(default)


def _count_sample(mean: float, stddev: float, rng: np.random.Generator) -> int:
    mean = max(_finite_float(mean), 0.0)
    stddev = max(_finite_float(stddev), 0.0)
    if mean <= 0.0:
        return 0
    variance = max(stddev**2, mean)
    if variance > mean + 1e-6:
        shape = max(mean**2 / max(variance - mean, 1e-6), 0.05)
        probability = shape / (shape + mean)
        return int(rng.negative_binomial(shape, probability))
    return int(rng.poisson(mean))


def _seasonality_multiplier(product_id: object, current_date: date) -> float:
    phase = 2.0 * math.pi * _stable_unit_interval(product_id, "annual-phase")
    amplitude = 0.08 + 0.17 * _stable_unit_interval(product_id, "annual-amplitude")
    annual = 1.0 + amplitude * math.sin(
        2.0 * math.pi * current_date.timetuple().tm_yday / 365.25 + phase
    )
    dow = current_date.weekday()
    weekday_bias = (_stable_unit_interval(product_id, f"dow-{dow}") - 0.5) * 0.16
    return max(0.55, annual * (1.0 + weekday_bias))


def build_demand_history(
    seed: pd.DataFrame,
    *,
    end_date: date,
    days: int = DEFAULT_OFFLINE_HISTORY_DAYS,
    row_budget: int = 500_000,
) -> pd.DataFrame:
    """Create full product-day histories with exact 28-day lags and 30-day targets."""

    if seed.empty:
        return pd.DataFrame()
    usable_days = max(days - 58, 1)  # 28 lag burn-in + 30 future-target burn-out.
    product_count = _sample_count(row_budget, usable_days, len(seed))
    ordered = seed.copy()
    ordered["_rank"] = ordered["product_id"].map(
        lambda value: _stable_unit_interval(value, "demand-product-sample")
    )
    ordered = ordered.sort_values("_rank").head(product_count).drop(columns="_rank")
    start_date = end_date - timedelta(days=days - 1)
    dates = [start_date + timedelta(days=offset) for offset in range(days)]
    rows: list[dict[str, object]] = []

    for item in ordered.to_dict(orient="records"):
        product_id = item["product_id"]
        rng = _rng_for(product_id, "demand-history")
        base_mean = max(_finite_float(item.get("avg_requested_units"), 0.0), 0.05)
        observed_std = max(
            _finite_float(item.get("std_requested_units"), math.sqrt(base_mean)),
            math.sqrt(base_mean),
        )
        price = max(_finite_float(item.get("retail_price_egp"), 0.0), 0.0)
        branches = max(_finite_float(item.get("avg_selling_branches"), 1.0), 1.0)
        tx_per_unit = max(
            _finite_float(item.get("avg_transactions_per_requested_unit"), 0.15), 0.15
        )
        lost_rate = min(max(_finite_float(item.get("lost_rate"), 0.0), 0.0), 0.30)
        margin = 0.10 + 0.15 * _stable_unit_interval(product_id, "margin")
        annual_trend = (_stable_unit_interval(product_id, "trend") - 0.5) * 0.18

        for index, current_date in enumerate(dates):
            progress = index / max(days - 1, 1)
            mean = base_mean * _seasonality_multiplier(product_id, current_date)
            mean *= max(0.70, 1.0 + annual_trend * (progress - 0.5))
            # Small promotion and supply/demand shock process. This intentionally
            # produces heavy-tail days so RMSE/P90 evaluation is meaningful.
            if rng.random() < 0.018:
                mean *= float(rng.uniform(1.4, 2.8))
            if rng.random() < 0.012:
                mean *= float(rng.uniform(0.35, 0.75))
            dynamic_std = max(
                observed_std * math.sqrt(max(mean / base_mean, 0.25)),
                math.sqrt(mean),
            )
            requested = _count_sample(mean, dynamic_std, rng)
            effective_lost_rate = min(max(lost_rate + float(rng.normal(0.0, 0.01)), 0.0), 0.35)
            fulfilled = (
                int(rng.binomial(requested, 1.0 - effective_lost_rate))
                if requested > 0
                else 0
            )
            lost = max(requested - fulfilled, 0)
            selling_branches = int(max(0, round(branches * (0.85 + 0.30 * rng.random()))))
            transactions = int(
                max(0, round(requested * tx_per_unit * (0.85 + 0.30 * rng.random())))
            )
            stockout_attempts = int(lost > 0) + int(lost >= 3 and rng.random() < 0.35)
            net_sales = fulfilled * price
            rows.append(
                {
                    "business_date": current_date,
                    "product_id": product_id,
                    "retail_price_egp": price,
                    "selling_branches": selling_branches,
                    "sales_transactions": transactions,
                    "units_sold": fulfilled,
                    "requested_units": requested,
                    "fulfilled_units": fulfilled,
                    "lost_units": lost,
                    "fill_rate": fulfilled / requested if requested > 0 else 1.0,
                    "stockout_attempts": stockout_attempts,
                    "net_sales_egp": net_sales,
                    "gross_profit_egp": net_sales * margin,
                    "day_of_week": ((current_date.weekday() + 1) % 7) + 1,
                    "month_of_year": current_date.month,
                    "lost_rate": lost / requested if requested > 0 else 0.0,
                }
            )

    frame = pd.DataFrame(rows).sort_values(["product_id", "business_date"]).reset_index(drop=True)
    grouped = frame.groupby("product_id", sort=False, group_keys=False)
    for lag in (1, 7, 14, 28):
        frame[f"requested_lag_{lag}"] = grouped["requested_units"].shift(lag)
    frame["requested_avg_7"] = grouped["requested_units"].transform(
        lambda series: series.shift(1).rolling(7, min_periods=7).mean()
    )
    frame["requested_avg_28"] = grouped["requested_units"].transform(
        lambda series: series.shift(1).rolling(28, min_periods=28).mean()
    )
    frame["requested_stddev_28"] = grouped["requested_units"].transform(
        lambda series: series.shift(1).rolling(28, min_periods=28).std(ddof=1)
    )
    frame["stockout_avg_7"] = grouped["stockout_attempts"].transform(
        lambda series: series.shift(1).rolling(7, min_periods=7).mean()
    )
    frame["demand_trend_7_28"] = (
        frame["requested_avg_7"] / frame["requested_avg_28"].clip(lower=1.0)
    )
    for horizon in (1, 7, 14, 30):
        frame[f"target_demand_{horizon}d"] = grouped["requested_units"].transform(
            lambda series, h=horizon: (
                series.shift(-1).iloc[::-1].rolling(h, min_periods=h).sum().iloc[::-1]
            )
        )
    required = ["requested_lag_28", "requested_avg_28", "target_demand_30d"]
    frame = frame.dropna(subset=required).reset_index(drop=True)
    if len(frame) > row_budget:
        # Product histories are equal length; selecting complete products preserves
        # the time axis and avoids chronological truncation.
        usable_per_product = int(frame.groupby("product_id").size().median())
        keep_products = max(1, row_budget // max(usable_per_product, 1))
        selected = (
            frame[["product_id"]]
            .drop_duplicates()
            .assign(
                _rank=lambda x: x["product_id"].map(
                    lambda value: _stable_unit_interval(value, "demand-final")
                )
            )
            .sort_values("_rank")
            .head(keep_products)["product_id"]
        )
        frame = frame[frame["product_id"].isin(set(selected))].reset_index(drop=True)
    return frame


def build_stockout_history(
    seed: pd.DataFrame,
    *,
    end_date: date,
    days: int = DEFAULT_OFFLINE_HISTORY_DAYS,
    row_budget: int = 500_000,
) -> pd.DataFrame:
    """Simulate branch-product inventory trajectories with observed future labels.

    The simulator is calibrated from observed branch-product demand, current stock,
    supplier reliability and the observed loss/stockout rates. It intentionally
    models heterogeneous inventory regimes (normal, lean and disruption-prone)
    rather than forcing labels. Future stockout labels are then derived only from
    subsequent simulated inventory depletion/replenishment events, preserving a
    leakage-safe supervised target for the synthetic portfolio environment.
    """

    if seed.empty:
        return pd.DataFrame()
    usable_days = max(days - 49, 1)  # 28-day feature burn-in + 21-day future replay.
    pair_count = _sample_count(row_budget, usable_days, len(seed))
    ordered = seed.copy()
    ordered["_pair_key"] = (
        ordered["branch_id"].astype(str) + "|" + ordered["product_id"].astype(str)
    )
    ordered["_rank"] = ordered["_pair_key"].map(
        lambda value: _stable_unit_interval(value, "stockout-pair")
    )
    ordered = ordered.sort_values("_rank").head(pair_count).drop(columns="_rank")
    start_date = end_date - timedelta(days=days - 1)
    dates = [start_date + timedelta(days=offset) for offset in range(days)]
    rows: list[dict[str, object]] = []

    for item in ordered.to_dict(orient="records"):
        pair_key = item["_pair_key"]
        rng = _rng_for(pair_key, "stockout-history")
        base_mean = max(_finite_float(item.get("avg_requested_units"), 0.0), 0.08)
        observed_std = max(
            _finite_float(item.get("std_requested_units"), math.sqrt(base_mean)),
            math.sqrt(base_mean),
        )
        active_rate = min(
            max(_finite_float(item.get("active_day_rate"), 0.25), 0.05), 1.0
        )
        nominal_reliability = min(
            max(_finite_float(item.get("supplier_reliability"), 0.90), 0.55), 0.995
        )
        lead_days = int(
            max(round(_finite_float(item.get("supplier_lead_time_days"), 3.0)), 1)
        )
        observed_stockout_rate = min(
            max(_finite_float(item.get("stockout_rate"), 0.0), 0.0), 0.50
        )
        observed_lost_rate = min(
            max(_finite_float(item.get("lost_rate"), 0.0), 0.0), 0.50
        )

        # Calibrate latent pair fragility from the observed 15-day portfolio signal,
        # while retaining deterministic heterogeneity for pairs with no observed loss.
        # This parameter affects the inventory process only; it is not exposed as a
        # training feature or copied into the future label.
        fragility = min(
            max(
                0.06
                + 2.50 * observed_stockout_rate
                + 3.50 * observed_lost_rate
                + 0.14 * rng.random(),
                0.04,
            ),
            0.70,
        )
        reliability = min(max(nominal_reliability - 0.18 * fragility, 0.50), 0.995)

        current_available = max(_finite_float(item.get("available_units"), 0.0), 0.0)
        observed_coverage_days = min(current_available / max(base_mean, 0.08), 21.0)
        policy_coverage_days = lead_days + 6.0
        start_coverage_days = (
            0.35 * observed_coverage_days + 0.65 * policy_coverage_days
        ) * (1.0 - 0.50 * fragility)
        start_coverage_days = min(
            max(start_coverage_days, max(1.0, lead_days * 0.55)),
            lead_days + 12.0,
        )
        available = float(max(round(base_mean * start_coverage_days), 0))

        safety_days = max(0.75, 2.75 - 2.25 * fragility)
        reorder_point = max(base_mean * (lead_days + safety_days), 2.0)
        target_coverage_days = max(lead_days + 4.0, lead_days + 9.0 - 4.5 * fragility)
        target_stock = max(
            base_mean * target_coverage_days
            + (1.15 + 0.55 * (1.0 - fragility))
            * observed_std
            * math.sqrt(max(target_coverage_days, 1.0)),
            reorder_point + 2.0,
        )
        review_miss_rate = min(0.04 + 0.24 * fragility, 0.30)
        spike_probability = min(0.015 + 0.060 * fragility, 0.08)

        # A subset of pairs experiences a bounded supplier disruption episode.
        # This generates realistic rare-event variation without assigning labels.
        has_disruption = rng.random() < min(0.10 + 0.35 * fragility, 0.40)
        disruption_start = int(rng.integers(45, max(46, days - 35))) if has_disruption else -1
        disruption_length = int(rng.integers(4, 13)) if has_disruption else 0
        disruption_end = disruption_start + disruption_length
        inbound_queue: list[tuple[int, float]] = []

        for day_index, current_date in enumerate(dates):
            disrupted = has_disruption and disruption_start <= day_index < disruption_end
            day_reliability = max(reliability - (0.22 if disrupted else 0.0), 0.35)

            delivered = 0.0
            remaining_queue: list[tuple[int, float]] = []
            for due_index, quantity in inbound_queue:
                if due_index <= day_index:
                    if rng.random() <= day_reliability:
                        # Real suppliers can short-ship; disruption days are more severe.
                        fill_floor = 0.55 if disrupted else 0.82
                        fill_ratio = float(rng.uniform(fill_floor, 1.0))
                        delivered += quantity * fill_ratio
                        short = quantity * (1.0 - fill_ratio)
                        if short >= 1.0:
                            remaining_queue.append((day_index + 1, short))
                    else:
                        retry_delay = 1 + int(rng.integers(0, 4 if disrupted else 3))
                        remaining_queue.append((day_index + retry_delay, quantity))
                else:
                    remaining_queue.append((due_index, quantity))
            inbound_queue = remaining_queue
            available += delivered

            seasonal = _seasonality_multiplier(item["product_id"], current_date)
            active = rng.random() < active_rate
            mean = base_mean * seasonal if active else 0.0
            if rng.random() < spike_probability:
                mean *= float(rng.uniform(1.6, 3.8))
            if disrupted and active:
                # Demand continues during supply disruption and may even increase.
                mean *= float(rng.uniform(1.0, 1.35))
            requested = _count_sample(
                mean,
                max(observed_std, math.sqrt(max(mean, 0.0))),
                rng,
            )
            fulfilled = int(min(requested, max(math.floor(available), 0)))
            lost = max(requested - fulfilled, 0)
            available = max(available - fulfilled, 0.0)
            stockout_today = int(requested > 0 and lost > 0)

            outstanding = float(sum(quantity for _, quantity in inbound_queue))
            if available + outstanding <= reorder_point and rng.random() > review_miss_rate:
                order_qty = max(math.ceil(target_stock - available - outstanding), 0)
                if order_qty > 0:
                    extra_delay_max = 3 + (4 if disrupted else int(round(2 * fragility)))
                    stochastic_lead = lead_days + int(rng.integers(0, max(extra_delay_max, 1)))
                    inbound_queue.append((day_index + stochastic_lead, float(order_qty)))
                    outstanding += float(order_qty)

            rows.append(
                {
                    "branch_id": item["branch_id"],
                    "product_id": item["product_id"],
                    "business_date": current_date,
                    "available_units": float(available),
                    "requested_units": float(requested),
                    "fulfilled_units": float(fulfilled),
                    "lost_units": float(lost),
                    "stockout_today": int(stockout_today),
                    "supplier_lead_time_days": float(lead_days),
                    "supplier_reliability": float(reliability),
                    "inbound_units": float(outstanding),
                    "day_of_week": ((current_date.weekday() + 1) % 7) + 1,
                    "month_of_year": current_date.month,
                }
            )

    frame = (
        pd.DataFrame(rows)
        .sort_values(["branch_id", "product_id", "business_date"])
        .reset_index(drop=True)
    )
    keys = ["branch_id", "product_id"]
    grouped = frame.groupby(keys, sort=False, group_keys=False)
    frame["requested_avg_7"] = grouped["requested_units"].transform(
        lambda series: series.shift(1).rolling(7, min_periods=7).mean()
    )
    frame["requested_avg_28"] = grouped["requested_units"].transform(
        lambda series: series.shift(1).rolling(28, min_periods=28).mean()
    )
    frame["requested_stddev_28"] = grouped["requested_units"].transform(
        lambda series: series.shift(1).rolling(28, min_periods=28).std(ddof=1)
    )
    lost_28 = grouped["lost_units"].transform(
        lambda series: series.shift(1).rolling(28, min_periods=28).sum()
    )
    requested_28 = grouped["requested_units"].transform(
        lambda series: series.shift(1).rolling(28, min_periods=28).sum()
    )
    frame["lost_rate_28"] = lost_28 / requested_28.clip(lower=1.0)
    frame["stockout_rate_28"] = grouped["stockout_today"].transform(
        lambda series: series.shift(1).rolling(28, min_periods=28).mean()
    )
    frame["target_stockout_7d"] = grouped["stockout_today"].transform(
        lambda series: series.shift(-1).iloc[::-1].rolling(7, min_periods=7).max().iloc[::-1]
    )
    for horizon in (7, 14, 21):
        frame[f"future_demand_{horizon}d"] = grouped["requested_units"].transform(
            lambda series, h=horizon: (
                series.shift(-1).iloc[::-1].rolling(h, min_periods=h).sum().iloc[::-1]
            )
        )
    frame["avg_daily_requested_units"] = frame["requested_avg_28"]
    frame["demand_stddev_units"] = frame["requested_stddev_28"]
    required = ["requested_avg_28", "target_stockout_7d", "future_demand_21d"]
    frame = frame.dropna(subset=required).reset_index(drop=True)
    if len(frame) > row_budget:
        sizes = frame.groupby(keys).size()
        usable_per_pair = int(sizes.median())
        keep_pairs = max(1, row_budget // max(usable_per_pair, 1))
        pair_frame = frame[keys].drop_duplicates().copy()
        pair_frame["_key"] = (
            pair_frame["branch_id"].astype(str) + "|" + pair_frame["product_id"].astype(str)
        )
        pair_frame["_rank"] = pair_frame["_key"].map(
            lambda value: _stable_unit_interval(value, "stockout-final")
        )
        selected = set(pair_frame.sort_values("_rank").head(keep_pairs)["_key"])
        row_keys = frame["branch_id"].astype(str) + "|" + frame["product_id"].astype(str)
        frame = frame[row_keys.isin(selected)].reset_index(drop=True)
    return frame

def persist_offline_history(
    demand: pd.DataFrame,
    stockout: pd.DataFrame,
    *,
    root: Path,
    observed_history_days: int,
    generated_history_days: int,
) -> OfflineHistorySummary:
    root.mkdir(parents=True, exist_ok=True)
    demand.to_parquet(root / "demand_training_history.parquet", index=False, compression="snappy")
    stockout.to_parquet(
        root / "stockout_training_history.parquet", index=False, compression="snappy"
    )
    summary = OfflineHistorySummary(
        observed_history_days=observed_history_days,
        generated_history_days=generated_history_days,
        demand_rows=len(demand),
        stockout_rows=len(stockout),
    )
    pd.DataFrame([summary.__dict__ if hasattr(summary, "__dict__") else {
        "observed_history_days": summary.observed_history_days,
        "generated_history_days": summary.generated_history_days,
        "demand_rows": summary.demand_rows,
        "stockout_rows": summary.stockout_rows,
        "provenance": summary.provenance,
    }]).to_json(root / "offline_history_summary.json", orient="records", indent=2)
    return summary
