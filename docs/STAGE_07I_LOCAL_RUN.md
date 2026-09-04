# Stage 7I Local Run

```powershell
$env:PHARMSTOCK_BQ_PROJECT="pharmstock-ai-bq2-2026"
$env:PHARMSTOCK_BQ_SANDBOX="1"

.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest tests\test_stage7i_cdc.py -q

# Dry-run: starts/verifies local CDC services and inspects pending offsets/storage.
.\.venv\Scripts\python.exe scripts\run_stage7i_cdc.py

# Initialize delta/current datasets and process one bounded CDC micro-batch.
.\.venv\Scripts\python.exe scripts\run_stage7i_cdc.py --execute

# Continuous mode for SQL practice / operational CDC.
.\.venv\Scripts\python.exe scripts\run_stage7i_cdc.py --execute --watch --interval 60
```

Do not use Stage 7H reset/reload commands after Stage 7I starts. Stage 7I has no reset flag.
