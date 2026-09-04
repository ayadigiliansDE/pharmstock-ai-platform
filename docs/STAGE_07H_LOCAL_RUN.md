# Stage 7H Local Run

## 1. Install cloud/dbt extras

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,gcp,analytics]"
```

## 2. Tests and lint

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
```

## 3. Safe local preflight

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 7h
```

Expected terminal status:

```text
STAGE_7H_PREFLIGHT_STATUS=PASS
```

This command performs no cloud mutation. Inspect:

```text
artifacts/stage7h/preflight.json
```

If `Cloud ready hint` is `NO`, configure the project and ADC before cloud execution.

## 4. Configure BigQuery

```powershell
$env:PHARMSTOCK_BQ_PROJECT="YOUR_GCP_PROJECT_ID"
$env:PHARMSTOCK_BQ_LOCATION="EU"
$env:PHARMSTOCK_BQ_REBUILD_DATASET="pharmstock_ops_rebuild"
$env:PHARMSTOCK_DBT_BASE_DATASET="pharmstock"
```

Authenticate with Google Application Default Credentials using your normal Google Cloud workflow.

Re-run the preflight until `Cloud ready hint: YES`.

## 5. Explicit cloud deployment

Dry run first:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7h_cloud.py
```

Actual deployment:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7h_cloud.py --execute --replace
```

Final expected status:

```text
STAGE_7H_STATUS=PASS
```

Do not rerun Stage 7E, 7F or 7G merely to execute Stage 7H. Stage 7H consumes the already accepted
Stage 7G rebuild package and preserves `cdc_resume_offsets.json`.
