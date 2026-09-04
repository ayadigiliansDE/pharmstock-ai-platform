PharmStock AI Platform V2 — Stage 7K v0.34.2 Tail-Risk Regression Fix

Purpose
-------
Restore the v0.34.2 demand tail-risk guard that was lost from ml/stage7k/train.py
while the rest of the repository remained on v0.34.2.

Restored behavior
-----------------
- SYNTHETIC_CALIBRATED_OFFLINE_BACKFILL => demand ML blend capped at 0.15.
- Observed warehouse history (>= configured minimum, currently 90 distinct days) => cap 1.00.
- Validation-only blend selection remains conservative.
- Baseline safety fallback remains enabled.
- Strict holdout/backtesting scientific gates are unchanged.
- No BigQuery writes and no cloud mutations are introduced.

Apply
-----
Extract the CONTENTS of this ZIP directly into:
D:\Data_Engineer_Work_With_VSCode\Projects\pharmstock-ai-platform-v2

Choose Replace/Overwrite when asked.

Validate
--------
From the repository root in PowerShell:

$env:PHARMSTOCK_BQ_PROJECT="pharmstock-ai-bq2-2026"
$env:PHARMSTOCK_BQ_SANDBOX="1"

.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest tests\test_stage7k_ml.py -q
.\.venv\Scripts\python.exe scripts\run_stage7k.py --execute --no-build

Expected unit result
--------------------
31 passed

Required live final markers
---------------------------
STAGE_7K_SCIENTIFIC_VALIDATION_STATUS=PASS
STAGE_7K_MODEL_QUALITY_STATUS=PASS
STAGE_7K_TRAINING_STATUS=PASS
STAGE_7K_MLFLOW_STATUS=PASS
STAGE_7K_REGISTRY_STATUS=PASS
STAGE_7K_SERVING_STATUS=PASS
STAGE_7K_PRODUCTION_READINESS_STATUS=PASS
STAGE_7K_STATUS=PASS
