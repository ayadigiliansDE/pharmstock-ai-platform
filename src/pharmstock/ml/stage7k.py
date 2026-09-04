"""Stage 7K production ML contracts, scientific validation and cloud-ready planning.

BigQuery remains a read-only feature source. Predictive ML is used only where
historical labels are defensible. Replenishment and expiry components remain
explicit decision/risk engines and are validated with historical replay or
stochastic calibration instead of fabricated supervised targets.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

STAGE7K_VERSION: Final[str] = "0.34.2"
STAGE7K_ROOT: Final[Path] = Path("artifacts/stage7k")
STAGE7K_SUCCESS: Final[Path] = STAGE7K_ROOT / "_SUCCESS"
STAGE7J_SUCCESS: Final[Path] = Path("artifacts/stage7j/_SUCCESS")
DEFAULT_GOLD_DATASET: Final[str] = "pharmstock_rebuild_gold"
DEFAULT_CURRENT_DATASET: Final[str] = "pharmstock_ops_current"
DEFAULT_MLFLOW_URI: Final[str] = "http://localhost:5001"
DEFAULT_SERVING_URI: Final[str] = "http://localhost:8090"
DEFAULT_MAX_TRAINING_ROWS: Final[int] = 500_000
DEFAULT_MAX_QUERY_GIB: Final[float] = 8.0
DEFAULT_WARN_GIB: Final[float] = 8.2
DEFAULT_HARD_STOP_GIB: Final[float] = 8.5
DEFAULT_OFFLINE_HISTORY_DAYS: Final[int] = 365
MIN_OBSERVED_HISTORY_DAYS: Final[int] = 90
DEFAULT_REVIEW_PERIOD_DAYS: Final[float] = 7.0
DEFAULT_SERVICE_Z: Final[float] = 1.65
DEMAND_HORIZONS_DAYS: Final[tuple[int, ...]] = (1, 7, 14, 30)


@dataclass(frozen=True, slots=True)
class ModelSpec:
    key: str
    registered_name: str
    task: str
    model_kind: str
    source: str
    target: str


MODEL_SPECS: Final[tuple[ModelSpec, ...]] = (
    ModelSpec(
        key="demand_forecast",
        registered_name="pharmstock_demand_forecast",
        task="multi_horizon_regression",
        model_kind="predictive_ml",
        source="mart7h_product_daily_performance",
        target="future cumulative requested units at 1/7/14/30 day horizons",
    ),
    ModelSpec(
        key="stockout_risk",
        registered_name="pharmstock_stockout_risk",
        task="binary_probability",
        model_kind="predictive_risk_ml",
        source="stock_movement + demand_attempt + supplier/purchase_order",
        target="observed stockout event in next 7 days",
    ),
    ModelSpec(
        key="reorder_recommendation",
        registered_name="pharmstock_reorder_recommendation",
        task="prescriptive_regression",
        model_kind="service_level_replenishment_policy",
        source="historical inventory/demand replay + supplier/purchase_order",
        target="recommended order units",
    ),
    ModelSpec(
        key="expiry_slow_moving_risk",
        registered_name="pharmstock_expiry_slow_moving_risk",
        task="probability",
        model_kind="probabilistic_sell_through_policy",
        source="stock_batch + demand_attempt",
        target="probability inventory remains unsold at expiry",
    ),
)


@dataclass(frozen=True, slots=True)
class Stage7KConfig:
    project_id: str | None
    gold_dataset: str
    current_dataset: str
    location: str
    mlflow_uri: str
    serving_uri: str
    max_training_rows: int
    max_query_gib: float
    warn_gib: float
    hard_stop_gib: float

    def validate(self) -> None:
        if not self.project_id or not self.project_id.strip():
            raise ValueError("PHARMSTOCK_BQ_PROJECT cannot be empty")
        if self.max_training_rows < 1_000:
            raise ValueError("PHARMSTOCK_ML_MAX_TRAINING_ROWS must be >= 1000")
        if self.max_query_gib <= 0:
            raise ValueError("PHARMSTOCK_ML_MAX_QUERY_GIB must be positive")
        if not (0 < self.warn_gib < self.hard_stop_gib < 10):
            raise ValueError("storage thresholds must satisfy 0 < warn < hard stop < 10 GiB")


def config_from_environment() -> Stage7KConfig:
    config = Stage7KConfig(
        project_id=os.getenv("PHARMSTOCK_BQ_PROJECT", "").strip() or None,
        gold_dataset=os.getenv("PHARMSTOCK_BQ_GOLD_DATASET", DEFAULT_GOLD_DATASET).strip(),
        current_dataset=os.getenv(
            "PHARMSTOCK_BQ_CURRENT_DATASET", DEFAULT_CURRENT_DATASET
        ).strip(),
        location=os.getenv("PHARMSTOCK_BQ_LOCATION", "EU").strip(),
        mlflow_uri=os.getenv("MLFLOW_TRACKING_URI", DEFAULT_MLFLOW_URI).strip(),
        serving_uri=os.getenv("PHARMSTOCK_ML_SERVING_URI", DEFAULT_SERVING_URI).strip(),
        max_training_rows=int(
            os.getenv("PHARMSTOCK_ML_MAX_TRAINING_ROWS", str(DEFAULT_MAX_TRAINING_ROWS))
        ),
        max_query_gib=float(os.getenv("PHARMSTOCK_ML_MAX_QUERY_GIB", str(DEFAULT_MAX_QUERY_GIB))),
        warn_gib=float(os.getenv("PHARMSTOCK_BQ_WARN_GIB", str(DEFAULT_WARN_GIB))),
        hard_stop_gib=float(
            os.getenv("PHARMSTOCK_BQ_HARD_STOP_GIB", str(DEFAULT_HARD_STOP_GIB))
        ),
    )
    config.validate()
    return config


def storage_status(storage_gib: float, config: Stage7KConfig) -> str:
    if storage_gib >= config.hard_stop_gib:
        return "STOP"
    if storage_gib >= config.warn_gib:
        return "WARN"
    return "SAFE"


def _clip_probability(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return min(max(value, 0.0), 1.0)


def stockout_risk_score(
    *,
    available_units: float,
    avg_daily_requested_units: float,
    demand_stddev_units: float,
    supplier_lead_time_days: float,
    supplier_reliability: float,
    inbound_units: float,
) -> float:
    """Explainable fallback stockout pressure score used for stress tests only."""

    available = max(float(available_units), 0.0)
    mean_daily = max(float(avg_daily_requested_units), 0.0)
    sigma_daily = max(float(demand_stddev_units), 0.0)
    reliability = min(max(float(supplier_reliability), 0.50), 1.0)
    lead_days = max(float(supplier_lead_time_days), 1.0) / reliability
    effective_supply = available + max(float(inbound_units), 0.0) * reliability
    if mean_daily <= 0.0 and sigma_daily <= 0.0:
        return 0.0
    expected_demand = mean_daily * lead_days
    uncertainty = 1.28 * sigma_daily * math.sqrt(lead_days)
    stress_demand = expected_demand + uncertainty
    scale = max(stress_demand, 1.0)
    pressure = (stress_demand - effective_supply) / scale
    return _clip_probability(1.0 / (1.0 + math.exp(-4.0 * pressure)))


def reorder_recommendation_units(
    *,
    available_units: float,
    avg_daily_requested_units: float,
    demand_stddev_units: float,
    supplier_lead_time_days: float,
    supplier_reliability: float,
    inbound_units: float,
    review_period_days: float = DEFAULT_REVIEW_PERIOD_DAYS,
    service_z: float = DEFAULT_SERVICE_Z,
) -> float:
    """Order-up-to recommendation with reliability-adjusted lead time and safety stock."""

    available = max(float(available_units), 0.0)
    mean_daily = max(float(avg_daily_requested_units), 0.0)
    sigma_daily = max(float(demand_stddev_units), 0.0)
    reliability = min(max(float(supplier_reliability), 0.50), 1.0)
    lead_days = max(float(supplier_lead_time_days), 1.0) / reliability
    protection_days = lead_days + max(float(review_period_days), 0.0)
    cycle_demand = mean_daily * protection_days
    safety_stock = max(float(service_z), 0.0) * sigma_daily * math.sqrt(protection_days)
    effective_supply = available + max(float(inbound_units), 0.0) * reliability
    recommendation = max(cycle_demand + safety_stock - effective_supply, 0.0)
    return float(math.ceil(recommendation))


def expiry_risk_score(
    *,
    days_to_expiry: float,
    quantity_on_hand: float,
    avg_daily_units_sold: float,
    demand_stddev_units: float,
) -> float:
    """Approximate probability that inventory remains unsold at expiry.

    Demand to expiry is approximated as a non-negative aggregate Normal process.
    The score is the probability that cumulative demand is below current on-hand.
    This is materially more interpretable than an arbitrary logistic score and
    can be calibrated against count-demand simulation even when observed expiry
    losses are right-censored in the historical source.
    """

    days = float(days_to_expiry)
    on_hand = max(float(quantity_on_hand), 0.0)
    if on_hand <= 0:
        return 0.0
    if days <= 0:
        return 1.0
    velocity = max(float(avg_daily_units_sold), 0.0)
    sigma_daily = max(float(demand_stddev_units), 0.0)
    mean_sales = velocity * days
    sigma_sales = sigma_daily * math.sqrt(max(days, 1.0))
    if sigma_sales <= 1e-9:
        return 1.0 if mean_sales < on_hand else 0.0
    z = (on_hand - 0.5 - mean_sales) / sigma_sales
    return _clip_probability(0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))



def history_coverage_sql(config: Stage7KConfig) -> str:
    """Return observed temporal coverage without mutating BigQuery."""

    gold = f"{config.project_id}.{config.gold_dataset}.mart7h_product_daily_performance"
    demand = f"{config.project_id}.{config.current_dataset}.pos__demand_attempt"
    return f"""
WITH gold_coverage AS (
  SELECT
    MIN(business_date) AS min_date,
    MAX(business_date) AS max_date,
    COUNT(DISTINCT business_date) AS distinct_days
  FROM `{gold}`
), demand_coverage AS (
  SELECT
    MIN(DATE(transaction_ts)) AS min_date,
    MAX(DATE(transaction_ts)) AS max_date,
    COUNT(DISTINCT DATE(transaction_ts)) AS distinct_days
  FROM `{demand}`
)
SELECT
  g.min_date AS gold_min_date,
  g.max_date AS gold_max_date,
  g.distinct_days AS gold_distinct_days,
  d.min_date AS demand_min_date,
  d.max_date AS demand_max_date,
  d.distinct_days AS demand_distinct_days
FROM gold_coverage AS g
CROSS JOIN demand_coverage AS d
""".strip()


def demand_calibration_seed_sql(config: Stage7KConfig) -> str:
    """Observed product aggregates used only to calibrate zero-cost offline history."""

    table = f"{config.project_id}.{config.gold_dataset}.mart7h_product_daily_performance"
    return f"""
WITH product_stats AS (
  SELECT
    product_id,
    ANY_VALUE(retail_price_egp) AS retail_price_egp,
    AVG(requested_units) AS avg_requested_units,
    STDDEV_SAMP(requested_units) AS std_requested_units,
    AVG(selling_branches) AS avg_selling_branches,
    SAFE_DIVIDE(SUM(sales_transactions), GREATEST(SUM(requested_units), 1))
      AS avg_transactions_per_requested_unit,
    SAFE_DIVIDE(SUM(lost_units), GREATEST(SUM(requested_units), 1)) AS lost_rate
  FROM `{table}`
  GROUP BY product_id
)
SELECT *
FROM product_stats
WHERE avg_requested_units IS NOT NULL
ORDER BY FARM_FINGERPRINT(CAST(product_id AS STRING))
LIMIT 5000
""".strip()


def stockout_calibration_seed_sql(config: Stage7KConfig) -> str:
    """Observed branch-product aggregates used to seed offline inventory trajectories."""

    demand = f"{config.project_id}.{config.current_dataset}.pos__demand_attempt"
    inventory = f"{config.project_id}.{config.current_dataset}.inventory__inventory_position"
    purchase_order = f"{config.project_id}.{config.current_dataset}.procurement__purchase_order"
    supplier = f"{config.project_id}.{config.current_dataset}.procurement__supplier"
    return f"""
WITH daily AS (
  SELECT
    branch_id,
    product_id,
    DATE(transaction_ts) AS business_date,
    SUM(requested_units) AS requested_units,
    SUM(lost_units) AS lost_units,
    MAX(CASE WHEN outcome = 'OUT_OF_STOCK' THEN 1 ELSE 0 END) AS stockout_today
  FROM `{demand}`
  GROUP BY 1, 2, 3
), coverage AS (
  SELECT COUNT(DISTINCT business_date) AS total_days FROM daily
), pair_stats AS (
  SELECT
    branch_id,
    product_id,
    COUNT(*) AS active_days,
    AVG(requested_units) AS avg_requested_units,
    STDDEV_SAMP(requested_units) AS std_requested_units,
    SAFE_DIVIDE(SUM(lost_units), GREATEST(SUM(requested_units), 1)) AS lost_rate,
    AVG(stockout_today) AS stockout_rate
  FROM daily
  GROUP BY 1, 2
), supplier_by_branch AS (
  SELECT branch_id, nominal_lead_time_days, reliability_score
  FROM (
    SELECT
      po.branch_id,
      s.nominal_lead_time_days,
      s.reliability_score,
      ROW_NUMBER() OVER (PARTITION BY po.branch_id ORDER BY po.ordered_at DESC) AS rn
    FROM `{purchase_order}` AS po
    JOIN `{supplier}` AS s USING (supplier_id)
  )
  WHERE rn = 1
)
SELECT
  p.branch_id,
  p.product_id,
  p.avg_requested_units,
  p.std_requested_units,
  p.lost_rate,
  p.stockout_rate,
  SAFE_DIVIDE(p.active_days, GREATEST(c.total_days, 1)) AS active_day_rate,
  GREATEST(COALESCE(i.on_hand_units, 0) - COALESCE(i.reserved_units, 0), 0) AS available_units,
  COALESCE(s.nominal_lead_time_days, 3) AS supplier_lead_time_days,
  COALESCE(s.reliability_score, 0.90) AS supplier_reliability
FROM pair_stats AS p
CROSS JOIN coverage AS c
LEFT JOIN `{inventory}` AS i USING (branch_id, product_id)
LEFT JOIN supplier_by_branch AS s USING (branch_id)
WHERE p.avg_requested_units > 0
ORDER BY FARM_FINGERPRINT(CONCAT(CAST(p.branch_id AS STRING), '|', CAST(p.product_id AS STRING)))
LIMIT 5000
""".strip()


def product_temporal_feature_sql(config: Stage7KConfig) -> str:
    """Full-history product sample for multi-horizon demand forecasting.

    The query chooses a deterministic set of complete product histories sized to
    the configured row budget. This preserves the full time axis for each sampled
    product instead of truncating the earliest/latest dates with a row LIMIT.
    """

    table = f"{config.project_id}.{config.gold_dataset}.mart7h_product_daily_performance"
    return f"""
WITH bounds AS (
  SELECT MIN(business_date) AS min_date, MAX(business_date) AS max_date
  FROM `{table}`
), product_values AS (
  SELECT product_id, ANY_VALUE(retail_price_egp) AS retail_price_egp
  FROM `{table}`
  GROUP BY product_id
), ranked_products AS (
  SELECT
    product_id,
    retail_price_egp,
    ROW_NUMBER() OVER (ORDER BY FARM_FINGERPRINT(CAST(product_id AS STRING))) AS sample_rank
  FROM product_values
), sample_parameters AS (
  SELECT
    GREATEST(
      1,
      LEAST(
        (SELECT COUNT(*) FROM product_values),
        CAST(
          FLOOR(
            {config.max_training_rows} / GREATEST(DATE_DIFF(max_date, min_date, DAY) + 1, 1)
          ) AS INT64
        )
      )
    ) AS sampled_products
  FROM bounds
), products AS (
  SELECT rp.product_id, rp.retail_price_egp
  FROM ranked_products AS rp
  CROSS JOIN sample_parameters AS sp
  WHERE rp.sample_rank <= sp.sampled_products
), source AS (
  SELECT t.*
  FROM `{table}` AS t
  JOIN products USING (product_id)
), calendar AS (
  SELECT business_date
  FROM bounds, UNNEST(GENERATE_DATE_ARRAY(min_date, max_date)) AS business_date
), grid AS (
  SELECT p.product_id, p.retail_price_egp, c.business_date
  FROM products AS p
  CROSS JOIN calendar AS c
), series AS (
  SELECT
    g.business_date,
    g.product_id,
    COALESCE(s.retail_price_egp, g.retail_price_egp, 0) AS retail_price_egp,
    COALESCE(s.selling_branches, 0) AS selling_branches,
    COALESCE(s.sales_transactions, 0) AS sales_transactions,
    COALESCE(s.units_sold, 0) AS units_sold,
    COALESCE(s.requested_units, 0) AS requested_units,
    COALESCE(s.fulfilled_units, 0) AS fulfilled_units,
    COALESCE(s.lost_units, 0) AS lost_units,
    COALESCE(s.fill_rate, 1.0) AS fill_rate,
    COALESCE(s.stockout_attempts, 0) AS stockout_attempts,
    COALESCE(s.net_sales_egp, 0) AS net_sales_egp,
    COALESCE(s.gross_profit_egp, 0) AS gross_profit_egp,
    EXTRACT(DAYOFWEEK FROM g.business_date) AS day_of_week,
    EXTRACT(MONTH FROM g.business_date) AS month_of_year,
    SAFE_DIVIDE(COALESCE(s.lost_units, 0), GREATEST(COALESCE(s.requested_units, 0), 1))
      AS lost_rate,
    LAG(COALESCE(s.requested_units, 0), 1) OVER w AS requested_lag_1,
    LAG(COALESCE(s.requested_units, 0), 7) OVER w AS requested_lag_7,
    LAG(COALESCE(s.requested_units, 0), 14) OVER w AS requested_lag_14,
    LAG(COALESCE(s.requested_units, 0), 28) OVER w AS requested_lag_28,
    AVG(COALESCE(s.requested_units, 0)) OVER (
      PARTITION BY g.product_id ORDER BY UNIX_DATE(g.business_date)
      RANGE BETWEEN 7 PRECEDING AND 1 PRECEDING
    ) AS requested_avg_7,
    AVG(COALESCE(s.requested_units, 0)) OVER (
      PARTITION BY g.product_id ORDER BY UNIX_DATE(g.business_date)
      RANGE BETWEEN 28 PRECEDING AND 1 PRECEDING
    ) AS requested_avg_28,
    STDDEV_SAMP(COALESCE(s.requested_units, 0)) OVER (
      PARTITION BY g.product_id ORDER BY UNIX_DATE(g.business_date)
      RANGE BETWEEN 28 PRECEDING AND 1 PRECEDING
    ) AS requested_stddev_28,
    AVG(COALESCE(s.stockout_attempts, 0)) OVER (
      PARTITION BY g.product_id ORDER BY UNIX_DATE(g.business_date)
      RANGE BETWEEN 7 PRECEDING AND 1 PRECEDING
    ) AS stockout_avg_7,
    SUM(COALESCE(s.requested_units, 0)) OVER (
      PARTITION BY g.product_id ORDER BY UNIX_DATE(g.business_date)
      RANGE BETWEEN 1 FOLLOWING AND 1 FOLLOWING
    ) AS target_demand_1d,
    SUM(COALESCE(s.requested_units, 0)) OVER (
      PARTITION BY g.product_id ORDER BY UNIX_DATE(g.business_date)
      RANGE BETWEEN 1 FOLLOWING AND 7 FOLLOWING
    ) AS target_demand_7d,
    SUM(COALESCE(s.requested_units, 0)) OVER (
      PARTITION BY g.product_id ORDER BY UNIX_DATE(g.business_date)
      RANGE BETWEEN 1 FOLLOWING AND 14 FOLLOWING
    ) AS target_demand_14d,
    SUM(COALESCE(s.requested_units, 0)) OVER (
      PARTITION BY g.product_id ORDER BY UNIX_DATE(g.business_date)
      RANGE BETWEEN 1 FOLLOWING AND 30 FOLLOWING
    ) AS target_demand_30d
  FROM grid AS g
  LEFT JOIN source AS s USING (product_id, business_date)
  WINDOW w AS (PARTITION BY g.product_id ORDER BY g.business_date)
)
SELECT
  *,
  SAFE_DIVIDE(requested_avg_7, GREATEST(requested_avg_28, 1.0)) AS demand_trend_7_28
FROM series
WHERE requested_lag_28 IS NOT NULL
  AND target_demand_1d IS NOT NULL
  AND target_demand_7d IS NOT NULL
  AND target_demand_14d IS NOT NULL
  AND target_demand_30d IS NOT NULL
ORDER BY business_date, product_id
""".strip()

def stockout_supervised_feature_sql(config: Stage7KConfig) -> str:
    """Historical branch-product sequences with a future 7-day stockout label.

    Complete histories are sampled at the branch-product grain using a
    deterministic cumulative-row budget. That keeps temporal continuity and
    avoids the bias introduced by a final chronological LIMIT.
    """

    movement = f"{config.project_id}.{config.current_dataset}.inventory__stock_movement"
    demand = f"{config.project_id}.{config.current_dataset}.pos__demand_attempt"
    purchase_order = f"{config.project_id}.{config.current_dataset}.procurement__purchase_order"
    supplier = f"{config.project_id}.{config.current_dataset}.procurement__supplier"
    return f"""
WITH daily_all AS (
  SELECT
    branch_id,
    product_id,
    DATE(transaction_ts) AS business_date,
    SUM(requested_units) AS requested_units,
    SUM(fulfilled_units) AS fulfilled_units,
    SUM(lost_units) AS lost_units,
    MAX(CASE WHEN outcome = 'OUT_OF_STOCK' THEN 1 ELSE 0 END) AS stockout_today
  FROM `{demand}`
  GROUP BY 1, 2, 3
), pair_stats AS (
  SELECT branch_id, product_id, COUNT(*) AS pair_days
  FROM daily_all
  GROUP BY 1, 2
), ranked_pairs AS (
  SELECT
    branch_id,
    product_id,
    pair_days,
    ROW_NUMBER() OVER (
      ORDER BY FARM_FINGERPRINT(
        CONCAT(CAST(branch_id AS STRING), '|', CAST(product_id AS STRING))
      )
    ) AS sample_rank,
    SUM(pair_days) OVER (
      ORDER BY FARM_FINGERPRINT(
        CONCAT(CAST(branch_id AS STRING), '|', CAST(product_id AS STRING))
      )
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cumulative_days
  FROM pair_stats
), sampled_pairs AS (
  SELECT branch_id, product_id
  FROM ranked_pairs
  WHERE cumulative_days <= {config.max_training_rows} OR sample_rank = 1
), sampled_demand AS (
  SELECT d.*
  FROM daily_all AS d
  JOIN sampled_pairs USING (branch_id, product_id)
), sampled_balance AS (
  SELECT
    m.branch_id,
    m.product_id,
    DATE(m.occurred_at) AS business_date,
    ARRAY_AGG(m.balance_after_units ORDER BY m.occurred_at DESC LIMIT 1)[OFFSET(0)]
      AS eod_balance
  FROM `{movement}` AS m
  JOIN sampled_pairs USING (branch_id, product_id)
  GROUP BY 1, 2, 3
), supplier_by_branch AS (
  SELECT branch_id, nominal_lead_time_days, reliability_score
  FROM (
    SELECT
      po.branch_id,
      s.nominal_lead_time_days,
      s.reliability_score,
      ROW_NUMBER() OVER (PARTITION BY po.branch_id ORDER BY po.ordered_at DESC) AS rn
    FROM `{purchase_order}` AS po
    JOIN `{supplier}` AS s USING (supplier_id)
  )
  WHERE rn = 1
), joined AS (
  SELECT d.*, b.eod_balance
  FROM sampled_demand AS d
  LEFT JOIN sampled_balance AS b USING (branch_id, product_id, business_date)
), features AS (
  SELECT
    branch_id,
    product_id,
    business_date,
    COALESCE(
      LAST_VALUE(eod_balance IGNORE NULLS) OVER (
        PARTITION BY branch_id, product_id ORDER BY business_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
      ),
      0
    ) AS available_units,
    AVG(requested_units) OVER (
      PARTITION BY branch_id, product_id ORDER BY UNIX_DATE(business_date)
      RANGE BETWEEN 7 PRECEDING AND 1 PRECEDING
    ) AS requested_avg_7,
    AVG(requested_units) OVER (
      PARTITION BY branch_id, product_id ORDER BY UNIX_DATE(business_date)
      RANGE BETWEEN 28 PRECEDING AND 1 PRECEDING
    ) AS requested_avg_28,
    STDDEV_SAMP(requested_units) OVER (
      PARTITION BY branch_id, product_id ORDER BY UNIX_DATE(business_date)
      RANGE BETWEEN 28 PRECEDING AND 1 PRECEDING
    ) AS requested_stddev_28,
    SAFE_DIVIDE(
      SUM(lost_units) OVER (
        PARTITION BY branch_id, product_id ORDER BY UNIX_DATE(business_date)
        RANGE BETWEEN 28 PRECEDING AND 1 PRECEDING
      ),
      GREATEST(
        SUM(COALESCE(requested_units, 0)) OVER (
          PARTITION BY branch_id, product_id ORDER BY UNIX_DATE(business_date)
          RANGE BETWEEN 28 PRECEDING AND 1 PRECEDING
        ),
        1
      )
    ) AS lost_rate_28,
    AVG(stockout_today) OVER (
      PARTITION BY branch_id, product_id ORDER BY UNIX_DATE(business_date)
      RANGE BETWEEN 28 PRECEDING AND 1 PRECEDING
    ) AS stockout_rate_28,
    MAX(stockout_today) OVER (
      PARTITION BY branch_id, product_id ORDER BY UNIX_DATE(business_date)
      RANGE BETWEEN 1 FOLLOWING AND 7 FOLLOWING
    ) AS target_stockout_7d,
    SUM(COALESCE(requested_units, 0)) OVER (
      PARTITION BY branch_id, product_id ORDER BY UNIX_DATE(business_date)
      RANGE BETWEEN 1 FOLLOWING AND 7 FOLLOWING
    ) AS future_demand_7d,
    SUM(COALESCE(requested_units, 0)) OVER (
      PARTITION BY branch_id, product_id ORDER BY UNIX_DATE(business_date)
      RANGE BETWEEN 1 FOLLOWING AND 14 FOLLOWING
    ) AS future_demand_14d,
    SUM(COALESCE(requested_units, 0)) OVER (
      PARTITION BY branch_id, product_id ORDER BY UNIX_DATE(business_date)
      RANGE BETWEEN 1 FOLLOWING AND 21 FOLLOWING
    ) AS future_demand_21d,
    requested_units,
    fulfilled_units,
    lost_units,
    EXTRACT(DAYOFWEEK FROM business_date) AS day_of_week,
    EXTRACT(MONTH FROM business_date) AS month_of_year
  FROM joined
)
SELECT
  f.*,
  COALESCE(s.nominal_lead_time_days, 3) AS supplier_lead_time_days,
  COALESCE(s.reliability_score, 0.90) AS supplier_reliability,
  0.0 AS inbound_units
FROM features AS f
LEFT JOIN supplier_by_branch AS s USING (branch_id)
WHERE requested_avg_28 IS NOT NULL
  AND target_stockout_7d IS NOT NULL
  AND future_demand_21d IS NOT NULL
ORDER BY business_date, branch_id, product_id
""".strip()

def inventory_policy_feature_sql(config: Stage7KConfig) -> str:
    """Current operational feature view retained for serving examples and sanity checks."""

    inventory = f"{config.project_id}.{config.current_dataset}.inventory__inventory_position"
    demand = f"{config.project_id}.{config.current_dataset}.pos__demand_attempt"
    purchase_order = f"{config.project_id}.{config.current_dataset}.procurement__purchase_order"
    purchase_line = f"{config.project_id}.{config.current_dataset}.procurement__purchase_order_line"
    supplier = f"{config.project_id}.{config.current_dataset}.procurement__supplier"
    return f"""
WITH as_of AS (
  SELECT MAX(DATE(transaction_ts)) AS as_of_date FROM `{demand}`
), daily AS (
  SELECT
    branch_id,
    product_id,
    DATE(transaction_ts) AS business_date,
    SUM(requested_units) AS requested_units,
    SUM(fulfilled_units) AS fulfilled_units,
    SUM(lost_units) AS lost_units
  FROM `{demand}`, as_of
  WHERE DATE(transaction_ts) >= DATE_SUB(as_of_date, INTERVAL 35 DAY)
  GROUP BY 1, 2, 3
), demand_stats AS (
  SELECT
    branch_id,
    product_id,
    AVG(requested_units) AS avg_daily_requested_units,
    STDDEV_SAMP(requested_units) AS demand_stddev_units,
    AVG(fulfilled_units) AS avg_daily_units_sold,
    SAFE_DIVIDE(SUM(lost_units), GREATEST(SUM(requested_units), 1)) AS historical_lost_rate
  FROM daily
  GROUP BY 1, 2
), latest_supplier AS (
  SELECT branch_id, nominal_lead_time_days, reliability_score
  FROM (
    SELECT
      po.branch_id,
      s.nominal_lead_time_days,
      s.reliability_score,
      ROW_NUMBER() OVER (PARTITION BY po.branch_id ORDER BY po.ordered_at DESC) AS rn
    FROM `{purchase_order}` AS po
    JOIN `{supplier}` AS s USING (supplier_id)
  )
  WHERE rn = 1
), inbound AS (
  SELECT
    po.branch_id,
    pol.product_id,
    SUM(pol.ordered_units) AS inbound_units
  FROM `{purchase_order}` AS po
  JOIN `{purchase_line}` AS pol USING (purchase_order_id)
  WHERE UPPER(COALESCE(po.status, '')) NOT IN ('RECEIVED', 'CANCELLED', 'CLOSED')
  GROUP BY 1, 2
)
SELECT
  COALESCE(i.on_hand_units, 0) AS on_hand_units,
  COALESCE(i.reserved_units, 0) AS reserved_units,
  GREATEST(COALESCE(i.on_hand_units, 0) - COALESCE(i.reserved_units, 0), 0)
    AS available_units,
  COALESCE(i.reorder_point_units, 0) AS reorder_point_units,
  COALESCE(d.avg_daily_requested_units, 0) AS avg_daily_requested_units,
  COALESCE(d.demand_stddev_units, 0) AS demand_stddev_units,
  COALESCE(d.avg_daily_units_sold, 0) AS avg_daily_units_sold,
  COALESCE(d.historical_lost_rate, 0) AS historical_lost_rate,
  COALESCE(ls.nominal_lead_time_days, 3) AS supplier_lead_time_days,
  COALESCE(ls.reliability_score, 0.90) AS supplier_reliability,
  COALESCE(ib.inbound_units, 0) AS inbound_units
FROM `{inventory}` AS i
LEFT JOIN demand_stats AS d USING (branch_id, product_id)
LEFT JOIN latest_supplier AS ls USING (branch_id)
LEFT JOIN inbound AS ib USING (branch_id, product_id)
WHERE MOD(
  ABS(FARM_FINGERPRINT(CONCAT(CAST(i.branch_id AS STRING), '|', CAST(i.product_id AS STRING)))),
  100
) < 8
LIMIT {config.max_training_rows}
""".strip()


def reorder_feature_sql(config: Stage7KConfig) -> str:
    """Backward-compatible alias for the current inventory policy feature query."""

    return inventory_policy_feature_sql(config)


def expiry_feature_sql(config: Stage7KConfig) -> str:
    """Stratified current-batch sample for sell-through / expiry risk validation.

    Sampling is balanced across expiry-horizon buckets so the evaluation is not
    dominated by long-dated inventory or biased toward only the nearest expiries.
    """

    gold = f"{config.project_id}.{config.gold_dataset}.mart7h_product_daily_performance"
    batches = f"{config.project_id}.{config.current_dataset}.inventory__stock_batch"
    demand = f"{config.project_id}.{config.current_dataset}.pos__demand_attempt"
    per_bucket = max(int(math.ceil(config.max_training_rows / 6)), 1)
    return f"""
WITH as_of AS (
  SELECT MAX(business_date) AS as_of_date FROM `{gold}`
), daily AS (
  SELECT
    branch_id,
    product_id,
    DATE(transaction_ts) AS business_date,
    SUM(fulfilled_units) AS units_sold,
    SUM(requested_units) AS requested_units
  FROM `{demand}`, as_of
  WHERE DATE(transaction_ts) >= DATE_SUB(as_of_date, INTERVAL 35 DAY)
    AND DATE(transaction_ts) <= as_of_date
  GROUP BY 1, 2, 3
), recent AS (
  SELECT
    branch_id,
    product_id,
    AVG(units_sold) AS avg_daily_units_sold,
    AVG(requested_units) AS avg_daily_requested_units,
    STDDEV_SAMP(requested_units) AS demand_stddev_units
  FROM daily
  GROUP BY 1, 2
), candidates AS (
  SELECT
    b.batch_id,
    a.as_of_date,
    b.expiry_date,
    DATE_DIFF(b.expiry_date, a.as_of_date, DAY) AS days_to_expiry,
    DATE_DIFF(a.as_of_date, DATE(b.received_at), DAY) AS received_age_days,
    COALESCE(b.quantity_received, 0) AS quantity_received,
    COALESCE(b.quantity_on_hand, 0) AS quantity_on_hand,
    COALESCE(b.purchase_cost_egp, 0) AS purchase_cost_egp,
    COALESCE(b.retail_unit_price_egp, 0) AS retail_unit_price_egp,
    COALESCE(r.avg_daily_units_sold, 0) AS avg_daily_units_sold,
    COALESCE(r.avg_daily_requested_units, 0) AS avg_daily_requested_units,
    COALESCE(r.demand_stddev_units, 0) AS demand_stddev_units,
    SAFE_DIVIDE(
      COALESCE(b.quantity_on_hand, 0),
      GREATEST(COALESCE(r.avg_daily_units_sold, 0), 0.1)
    ) AS coverage_days,
    CASE
      WHEN DATE_DIFF(b.expiry_date, a.as_of_date, DAY) <= 30 THEN '00_30'
      WHEN DATE_DIFF(b.expiry_date, a.as_of_date, DAY) <= 60 THEN '31_60'
      WHEN DATE_DIFF(b.expiry_date, a.as_of_date, DAY) <= 90 THEN '61_90'
      WHEN DATE_DIFF(b.expiry_date, a.as_of_date, DAY) <= 180 THEN '91_180'
      WHEN DATE_DIFF(b.expiry_date, a.as_of_date, DAY) <= 365 THEN '181_365'
      ELSE '366_plus'
    END AS expiry_bucket
  FROM `{batches}` AS b
  CROSS JOIN as_of AS a
  LEFT JOIN recent AS r USING (branch_id, product_id)
  WHERE COALESCE(b.quantity_on_hand, 0) > 0
), ranked AS (
  SELECT
    *,
    ROW_NUMBER() OVER (
      PARTITION BY expiry_bucket
      ORDER BY FARM_FINGERPRINT(CAST(batch_id AS STRING))
    ) AS bucket_rank
  FROM candidates
)
SELECT * EXCEPT(bucket_rank)
FROM ranked
WHERE bucket_rank <= {per_bucket}
ORDER BY expiry_bucket, batch_id
""".strip()


def stage7k_contract() -> dict[str, object]:
    return {
        "stage": "7K",
        "production_hardening": f"v{STAGE7K_VERSION}",
        "bigquery": {
            "mode": "READ_ONLY_FEATURE_SOURCE",
            "writes": False,
            "raw_copy": False,
            "feature_tables_created": False,
        },
        "sampling": {
            "strategy": "observed_if_sufficient_else_synthetic_calibrated_offline_backfill",
            "default_feature_row_budget": DEFAULT_MAX_TRAINING_ROWS,
            "warehouse_total_rows_are_not_training_rows": True,
            "demand_complete_product_histories": True,
            "stockout_complete_branch_product_histories": True,
            "expiry_horizon_stratified": True,
            "minimum_observed_history_days": MIN_OBSERVED_HISTORY_DAYS,
            "offline_backfill_days": DEFAULT_OFFLINE_HISTORY_DAYS,
            "offline_backfill_provenance": "SYNTHETIC_CALIBRATED_OFFLINE_BACKFILL",
        },
        "models": [
            {
                "key": spec.key,
                "registered_name": spec.registered_name,
                "task": spec.task,
                "model_kind": spec.model_kind,
                "source": spec.source,
                "target": spec.target,
            }
            for spec in MODEL_SPECS
        ],
        "quality": {
            "strict_champion_gate": True,
            "demand": (
                "multi-horizon 1/7/14/30 day cumulative demand + conservative hybrid ML/baseline "
                "forecasting + temporal holdout + rolling-origin backtest + non-inferiority gates"
            ),
            "stockout": (
                "future-7d stockout label + temporal holdout + imbalance-aware training + "
                "validation-only operating-threshold selection + PR-AUC/ROC-AUC/Brier/"
                "calibration/top-k metrics"
            ),
            "reorder": (
                "service-level order-up-to policy + historical future-demand replay + stockout/"
                "overstock trade-off metrics"
            ),
            "expiry": (
                "sell-through probability + stochastic count-demand calibration + censored-cohort "
                "disclosure + monotonic stress scenarios"
            ),
            "target_leakage_allowed": False,
        },
        "mlflow": {
            "pinned_version": "3.15.2",
            "tracking": "LOCAL_DOCKER",
            "registry": "LOCAL_DOCKER",
            "artifact_store": "LOCAL_DOCKER_VOLUME",
            "candidate_alias": True,
            "champion_alias": "ONLY_AFTER_QUALITY_PASS",
        },
        "serving": {
            "mode": "ONE_LOCAL_MULTI_MODEL_API",
            "cloud_storage": False,
            "requires_all_champions_production_ready": True,
        },
        "streaming_ml": {
            "stage": "7K.5",
            "planned": True,
            "runtime": "Kafka + Spark Structured Streaming + local model serving",
            "retraining_per_event": False,
            "cloud_cost": False,
        },
        "cloud_ready": {
            "deployment_enabled": False,
            "billing_required_for_runtime": True,
            "default_action": "BLUEPRINT_ONLY_NO_CLOUD_MUTATION",
            "targets": ["Artifact Registry", "Vertex AI", "Cloud Run"],
        },
    }
