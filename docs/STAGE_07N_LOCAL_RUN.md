# Stage 7N local/cloud run

Set the accepted BigQuery Sandbox project:

```powershell
$env:PHARMSTOCK_BQ_PROJECT="pharmstock-ai-bq2-2026"
$env:PHARMSTOCK_BQ_SANDBOX="1"
```

Run lint and the Stage 7N contract tests:

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest tests\test_stage7n_powerbi_prod.py -q
```

Dry run:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7n_powerbi.py
```

Cloud/DB execution:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7n_powerbi.py --execute
```

Expected final markers:

```text
STAGE_7N_BIGQUERY_STATUS=PASS
STAGE_7N_POSTGRES_STATUS=PASS
STAGE_7N_GOVERNANCE_STATUS=PASS
STAGE_7N_STATUS=PASS
```

Generated Desktop build assets are under `artifacts/stage7n/`.
