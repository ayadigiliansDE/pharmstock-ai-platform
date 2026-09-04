# Stage 5D — Windows local run

Prerequisites: completed Stage 2B, 2D, 2F.1, 5C cloud execution, BigQuery ADC, and dbt.

```powershell
$env:PHARMSTOCK_BQ_PROJECT="pharmstock-ai-platform-2026"
$env:PHARMSTOCK_BQ_MASTER_DATASET="pharmstock_master"
$env:PHARMSTOCK_DBT_BASE_DATASET="pharmstock"
$env:PHARMSTOCK_BQ_LOCATION="EU"

.\.venv\Scripts\python.exe scripts\run_checkpoint.py 5d
```

The checkpoint creates `artifacts/stage5d/master_ready` and performs no cloud mutation.

BigQuery dry run:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage5d_bigquery.py `
  --project pharmstock-ai-platform-2026 `
  --dataset pharmstock_master `
  --location EU
```

Dimension dry run (run after the local snapshot; cloud master load is required only for execute):

```powershell
.\.venv\Scripts\python.exe scripts\run_stage5d_dimensions.py `
  --project pharmstock-ai-platform-2026 `
  --master-dataset pharmstock_master `
  --base-dataset pharmstock `
  --location EU
```
