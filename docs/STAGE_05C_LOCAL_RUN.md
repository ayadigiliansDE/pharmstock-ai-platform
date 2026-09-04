# Stage 5C — Windows / PowerShell Runbook

Run from the project root.

## 1. Install Stage 5C dependencies

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,gcp,analytics]"
```

Expected packages include dbt Core 1.12.x and dbt BigQuery 1.12.0.

## 2. Verify package version

```powershell
.\.venv\Scripts\python.exe -c "import pharmstock; print(pharmstock.__version__)"
```

Expected: `0.18.0`.

## 3. Run Python regressions and lint

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
```

Expected: 217 passed and `All checks passed!`.

## 4. Configure the current PowerShell session

```powershell
$env:PHARMSTOCK_BQ_PROJECT="pharmstock-ai-platform-2026"
$env:PHARMSTOCK_BQ_SOURCE_DATASET="pharmstock_silver"
$env:PHARMSTOCK_DBT_BASE_DATASET="pharmstock"
$env:PHARMSTOCK_BQ_LOCATION="EU"
```

## 5. Local-safe checkpoint

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 5c
```

This runs `dbt parse` only. It writes local dbt artifacts but performs no BigQuery mutation.
Expected final marker: `STAGE_5C_STATUS=PASS`.

## 6. Explicit dbt dry run

```powershell
.\.venv\Scripts\python.exe scripts\run_stage5c_dbt.py `
  --project pharmstock-ai-platform-2026 `
  --source-dataset pharmstock_silver `
  --base-dataset pharmstock `
  --location EU
```

Expected final marker: `STAGE_5C_DBT_MODE=DRY_RUN`.

## 7. Cloud execution

Only after the local checkpoint and dry run pass:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage5c_dbt.py `
  --project pharmstock-ai-platform-2026 `
  --source-dataset pharmstock_silver `
  --base-dataset pharmstock `
  --location EU `
  --execute
```

The command validates the Stage 5B cloud report, runs `dbt debug`, `dbt build`, generates dbt
documentation artifacts, verifies all seven Gold tables, and writes
`artifacts/stage5c/cloud_execution_report.json`.

Expected final marker: `STAGE_5C_CLOUD_STATUS=PASS`.
