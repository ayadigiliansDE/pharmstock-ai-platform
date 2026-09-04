# Stage 5B local run

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 5b
```

Expected final line:

```text
STAGE_5B_STATUS=PASS
```

The local checkpoint may report `Cloud ready now: NO`. That is expected until the optional BigQuery client, a project ID, and ADC are configured.

## Optional cloud preparation

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[gcp]"
$env:PHARMSTOCK_BQ_PROJECT="your-real-project-id"
$env:PHARMSTOCK_BQ_DATASET="pharmstock_silver"
$env:PHARMSTOCK_BQ_LOCATION="EU"
```

Set up Application Default Credentials using the Google Cloud CLI or an explicitly managed credential source. Never copy credential JSON into the repository.

Dry-run the live deployment command:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage5b_bigquery.py
```

Only after reviewing the project/dataset/location:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage5b_bigquery.py --execute --replace
```
