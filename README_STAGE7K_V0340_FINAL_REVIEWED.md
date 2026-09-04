# PharmStock Stage 7K v0.34.0 — Final Reviewed Scientific/MLOps Package

This package consolidates the Stage 7K fixes through v0.33.8 and replaces the
remaining brittle scientific gates with production-oriented behavior. It is
root-relative and is intended to be extracted directly over the repository root.

## What was fixed in the final review

### Demand forecasting

- Keeps 1/7/14/30-day cumulative horizons.
- Adds a validation-only conservative hybrid between the ML estimator and the
  strongest naive forecast.
- ML receives non-zero production weight only when it improves **both** MAE and
  RMSE on validation and survives rolling-origin robustness checks.
- If ML does not add reliable value, that horizon deliberately uses the stronger
  baseline. This is recorded as `baseline_safety_fallback`; weaker ML is never
  forced into production merely to claim an ML win.
- Final holdout acceptance is a strict non-inferiority gate plus absolute R2/WAPE
  requirements.
- Adds a target-horizon embargo: 30 days for demand splits and a purged
  rolling-origin training window, preventing future target windows from crossing
  temporal split boundaries.

### Stockout risk

- Preserves the leakage-safe future-7-day label and rare-event support checks.
- Removes the invalid fixed 0.5 operating-threshold behavior for a sub-1% event.
- Operating threshold is selected on validation data from the precision-recall
  curve subject to recall, lift and alert-budget constraints; top-decile scoring
  is the bounded fallback.
- Acceptance is prevalence-aware and emphasizes PR-AUC lift, ROC-AUC, Brier,
  calibration, Recall@Top10%, Lift@Top10%, operating recall/lift and alert rate.
- Adds a 7-day label embargo between temporal partitions.

### Reorder / expiry

- Reorder remains a prescriptive service-level policy and retains historical
  replay against a baseline policy.
- Expiry remains a probabilistic sell-through engine with stochastic calibration
  and explicit right-censoring disclosure. No fabricated expiry labels are added.

### MLOps / runtime

- MLflow remains pinned to `3.15.2`.
- Skops serialization retains the explicit custom-class allowlist.
- Stage runtime version is centralized at `0.34.0` and propagated to MLflow tags,
  contracts, reports and serving.
- GitPython warning noise is suppressed inside trainer/serving without weakening
  model lineage controls.
- Docker Compose orphan warnings are suppressed via `COMPOSE_IGNORE_ORPHANS=true`;
  no orphan container is removed.
- Existing failed/candidate MLflow versions remain as audit history; only a 4/4
  accepted set is promoted to `champion`.

### Cloud-ready export

- Still performs **zero cloud mutation** and **zero billing changes**.
- Fixed the local cloud bundle Python package layout so joblib models referencing
  `ml.stage7k.models.*` can be loaded in later Vertex/Cloud Run containers.
- Terraform billable-resource guard remains disabled by default.

## Local validation completed for this package

- Stage 7K unit/contract tests: **30 passed**.
- Python compile/AST checks: PASS.
- Docker Compose YAML parse: PASS.
- Conservative demand baseline-fallback smoke: PASS.
- Extracted rare-event threshold logic smoke: PASS.
- Cloud-ready local blueprint: PASS / no cloud mutation.
- Cloud bundle export + `ml.stage7k.models` joblib module-path round-trip: PASS.

The assistant environment does not contain the user's Docker daemon, BigQuery
credentials, or local Ruff executable, so the final live acceptance must still be
run in the project environment. No claim of `STAGE_7K_STATUS=PASS` is made until
that live run emits it.

## Apply and run

From the repository root after extracting this package:

```powershell
$env:PHARMSTOCK_BQ_PROJECT="pharmstock-ai-bq2-2026"
$env:PHARMSTOCK_BQ_SANDBOX="1"

.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest tests\test_stage7k_ml.py -q
.\.venv\Scripts\python.exe scripts\run_stage7k.py --execute --no-build
```

No Docker rebuild is required because no dependency was changed after the image
that already installed MLflow 3.15.2. Stage 7K source is bind-mounted.

Required final markers:

```text
STAGE_7K_SCIENTIFIC_VALIDATION_STATUS=PASS
STAGE_7K_MODEL_QUALITY_STATUS=PASS
STAGE_7K_TRAINING_STATUS=PASS
STAGE_7K_MLFLOW_STATUS=PASS
STAGE_7K_REGISTRY_STATUS=PASS
STAGE_7K_SERVING_STATUS=PASS
STAGE_7K_PRODUCTION_READINESS_STATUS=PASS
STAGE_7K_STATUS=PASS
```
