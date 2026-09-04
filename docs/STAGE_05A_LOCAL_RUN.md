# Stage 5A — Local Run Guide

Prerequisite: Stage 4B must have completed successfully and
`artifacts/stage4b/_SUCCESS` must exist.

## 1. Install / update the editable project

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## 2. Quality checks

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
```

## 3. Run the local BigQuery warehouse foundation

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 5a
```

This uses the pinned Spark Docker image but does not require Kafka to receive new data and does
not contact Google Cloud.

Expected ending:

```text
STAGE_5A_SPARK_STATUS=PASS
STAGE_5A_STATUS=PASS
```

Inspect:

```text
artifacts/stage5a/warehouse_ready/
artifacts/stage5a/contracts/
artifacts/stage5a/bigquery_bootstrap.sql
artifacts/stage5a/warehouse_catalog.json
artifacts/stage5a/cloud_load_plan.json
artifacts/stage5a/warehouse_verification.json
```

## 4. Optional cloud-loader dry run

No Google dependency is required for dry run:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage5a_bigquery_load.py
```

This prints the plan and performs no cloud mutation.

## 5. Optional real BigQuery load — only when deliberately requested

Install the optional client:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[gcp]"
```

Set a real project and authenticate with Application Default Credentials or another explicit
Google-supported credential mechanism. Then cloud replacement still requires both flags:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage5a_bigquery_load.py `
  --project YOUR_REAL_PROJECT_ID `
  --dataset pharmstock_silver `
  --location EU `
  --execute `
  --replace
```

Do not run the command with `--execute --replace` until the destination project and dataset
location are intentionally selected.
