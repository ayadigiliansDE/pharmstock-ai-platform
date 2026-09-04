# Stage 7K — Scientific ML + MLflow + Registry + Serving

Stage 7K turns the validated Stage 7H/7I analytical estate into a local-first
ML/MLOps layer while keeping BigQuery strictly read-only and preserving the
Sandbox storage guard.

## Production components

1. `pharmstock_demand_forecast` — cumulative demand forecasts for 1, 7, 14 and
   30 days. The production forecast is a conservative validation-selected hybrid:
   ML is blended with the strongest naive baseline only when it improves both MAE
   and RMSE; otherwise that horizon deliberately falls back to the stronger
   baseline instead of forcing weaker ML into production.
2. `pharmstock_stockout_risk` — calibrated probability of a stockout during the
   next 7 days. Training is imbalance-aware and the operating threshold is chosen
   on validation data from the precision-recall curve / alert budget rather than
   using an invalid fixed 0.5 threshold for a rare event.
3. `pharmstock_reorder_recommendation` — service-level replenishment policy,
   evaluated by historical future-demand replay, fill rate, lost units and
   overstock against a baseline replenishment policy.
4. `pharmstock_expiry_slow_moving_risk` — probability that current batch
   inventory remains unsold at expiry. Because the current synthetic portfolio is
   right-censored and has no defensible observed expiry-loss cohort, validation is
   stochastic calibration plus monotonic stress scenarios; no fake supervised
   expiry labels are created.

## Scientific acceptance

- Demand: temporal train/validation/test, rolling-origin backtests, three naive
  baselines, MAE/RMSE/R2/WAPE/sMAPE/median/P90/bias, demand-volume segments and a
  paired bootstrap non-inferiority check.
- Stockout: rare-event support checks, PR-AUC lift vs prevalence, ROC-AUC, Brier,
  calibration error, operating precision/recall/lift/alert rate, Recall@Top10%
  and Lift@Top10%.
- Reorder: policy-vs-baseline historical replay and scenario invariants.
- Expiry: stochastic count-demand calibration and scenario invariants with
  right-censoring disclosed in model metadata.
- All four candidates must pass before any new candidate set is promoted to
  `champion`.

## MLflow / serving

- MLflow is pinned to `3.15.2`.
- Tracking, registry metadata and artifacts remain local in Docker volumes.
- Skops serialization uses an explicit allowlist for the four internal model
  wrappers; no wildcard trust and no cloudpickle fallback is used.
- The serving API loads only `champion` versions tagged `production_ready=true`.
- Final acceptance includes 4/4 live inference smoke requests.

## Storage and cost safety

- BigQuery is a read-only feature source.
- No BigQuery feature table is materialized.
- No raw baseline copy is created.
- No DML, MERGE or streaming write is introduced by Stage 7K.
- Offline history used when observed time coverage is insufficient is local,
  explicitly tagged `SYNTHETIC_CALIBRATED_OFFLINE_BACKFILL`, and is never
  represented as observed pharmacy history.
- Cloud-ready files are blueprints only; deployment/billing remains disabled.
