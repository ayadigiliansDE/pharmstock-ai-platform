# Stage 7J v0.31.1 Ruff import-order hotfix

Fixes the single Ruff I001 finding in `dags/stage7j_pharmstock_health.py`.

Changes only import ordering. No Stage 7J logic, Airflow schedule, BigQuery access,
CDC offsets, or storage guard behavior is changed.

Apply by extracting this ZIP directly into the PharmStock project root.
