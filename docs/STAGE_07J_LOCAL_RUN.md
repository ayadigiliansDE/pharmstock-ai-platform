# Stage 7J Local Run

```powershell
$env:PHARMSTOCK_BQ_PROJECT="pharmstock-ai-bq2-2026"
$env:PHARMSTOCK_BQ_SANDBOX="1"

.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest tests\test_stage7j_observability.py -q
.\.venv\Scripts\python.exe scripts\run_stage7j.py
.\.venv\Scripts\python.exe scripts\run_stage7j.py --execute
```

The dry run performs no cloud mutation. `--execute` persists local monitoring artifacts and starts the local Airflow control plane. It does not copy or rewrite BigQuery data.
