# PharmStock AI Platform V2 — Stage 7K v0.32.2 Production Model Hardening

This patch hardens Stage 7K before Stage 7L. It is intentionally strict: no model is promoted to the MLflow `champion` alias until all four production-readiness gates pass.

## Why this patch exists

The first Stage 7K run proved the MLOps plumbing but exposed three model-quality problems:

- Stockout classifier: weak discrimination on the synthetic historical stockout labels.
- Reorder regressor: target leakage because the target was directly derived from feature columns.
- Expiry classifier: no useful positive class in the historical snapshot and a wall-clock-dependent label.

Those are modelling/data-semantics problems, not infrastructure problems. This patch removes the misleading formulations rather than hiding them behind high headline metrics.

## Hardened design

1. **Demand Forecast — predictive ML**
   - HistGradientBoostingRegressor.
   - Strict temporal train/validation/test split.
   - Candidate hyperparameter selection on validation MAE only.
   - Final test must achieve `R² >= 0.70` and beat a persistence baseline.
   - No random train/test leakage.

2. **Stockout Risk — probabilistic inventory policy**
   - Replaces the weak classifier trained on synthetic random stockout events.
   - Uses available stock, empirical demand rate/volatility, supplier lead time/reliability and inbound supply.
   - Returns a bounded stockout probability for the replenishment lead-time horizon.
   - Monotonic stress-scenario gates must pass before promotion.

3. **Reorder Recommendation — prescriptive replenishment policy**
   - Removes `target_stock_units`/self-formula target leakage completely.
   - Uses an order-up-to/service-level policy with demand uncertainty, supplier lead time, reliability, current available stock and inbound units.
   - Non-negative and supply-monotonic invariant gates are mandatory.

4. **Expiry / Slow-Moving Risk — probabilistic sell-through policy**
   - Removes the fabricated supervised expiry label.
   - Uses dataset `MAX(business_date)` as the as-of date, never `CURRENT_DATE()`.
   - Scores probability that inventory remains unsold at expiry using velocity and demand uncertainty.
   - Near-expiry/slow-moving stress scenarios must pass.

## Production controls added

- BigQuery remains **read only**.
- No feature tables are created in BigQuery.
- No raw baseline copy or DML/MERGE/streaming.
- Strict atomic champion promotion: all 4 candidates must pass before any new set is promoted.
- Serving fails closed: the old serving container is stopped while strict validation runs.
- Serving only loads MLflow champions tagged `production_ready=true`.
- `/health` reports production-ready model count.
- `/models` exposes model kind, quality gate and production-ready status.
- Inference rejects missing/non-numeric inputs and caps requests at 1,000 rows.
- Local model cards are written under `artifacts/stage7k/model_cards/`.
- Existing MLflow history is preserved; new versions are created rather than deleting v1.

## Fast execution after applying this patch

Dependencies did not change, so reuse the Stage 7K Docker image:

```powershell
$env:PHARMSTOCK_BQ_PROJECT="pharmstock-ai-bq2-2026"
$env:PHARMSTOCK_BQ_SANDBOX="1"

.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest tests\test_stage7k_ml.py -q
.\.venv\Scripts\python.exe scripts\run_stage7k.py
.\.venv\Scripts\python.exe scripts\run_stage7k.py --execute --no-build
```

Expected final acceptance markers:

```text
STAGE_7K_MODEL_QUALITY_STATUS=PASS
STAGE_7K_MLFLOW_STATUS=PASS
STAGE_7K_REGISTRY_STATUS=PASS
STAGE_7K_SERVING_STATUS=PASS
STAGE_7K_PRODUCTION_READINESS_STATUS=PASS
STAGE_7K_STATUS=PASS
```

Do not proceed to Stage 7L unless the production-readiness marker is PASS.
