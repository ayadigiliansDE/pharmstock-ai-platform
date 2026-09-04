# PharmStock Stage 7J v0.31.4 - Airflow Dependency Isolation Hotfix

## Why this hotfix exists
Stage 7J v0.31.3 used `_PIP_ADDITIONAL_REQUIREMENTS=google-cloud-bigquery==3.43.0`.
The Airflow 2.10.5 Python 3.12 image already contains a compatible Google Cloud stack,
including `google-cloud-bigquery` 3.20.1 in the observed runtime. Installing 3.43.0 at
container startup upgraded `protobuf` to 7.x, conflicting with the Google provider/cloud
packages bundled in the Airflow image, many of which require protobuf < 6.

Airflow itself warns that `_PIP_ADDITIONAL_REQUIREMENTS` is a development/test feature
and should not be used for production.

## Fix
- Removes `_PIP_ADDITIONAL_REQUIREMENTS` from the Airflow compose environment.
- Keeps the existing Airflow image and its compatible preinstalled dependency set intact.
- Adds a regression test so Stage 7J cannot reintroduce runtime pip mutation.
- Does not change BigQuery datasets, Airflow metadata DB, DAG logic, schedules, or cloud data.

## Validation performed
- Stage 7J tests: 9/9 PASS
- Relevant full regression: 139/139 PASS
- Python compile: PASS
- Ruff is not installed in the patch-building runtime; run project `.venv` Ruff locally.

## Apply
Extract at the repository root and overwrite matching files.

Then run:

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest tests\test_stage7j_observability.py -q
$env:PHARMSTOCK_BQ_PROJECT="pharmstock-ai-bq2-2026"
$env:PHARMSTOCK_BQ_SANDBOX="1"
.\.venv\Scripts\python.exe scripts\run_stage7j.py --execute
```

The v0.31.3 runner force-recreates Airflow webserver/scheduler, so the recreated containers
will start clean from the base image without the incompatible runtime pip install.
