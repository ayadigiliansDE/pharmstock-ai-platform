# Stage 7J v0.31.3 — Airflow DAG Discovery + Real Run History Hardening

This maintenance patch fixes a control-plane gap where the Airflow UI could be healthy while showing zero DAGs.

Changes:
- Forces recreation of Airflow webserver/scheduler after DB migration so bind mounts are refreshed.
- Declares `/opt/airflow/dags` explicitly as the Airflow DAG folder.
- Verifies `pharmstock_stage7j_health` is actually discovered, not merely that `/health` is green.
- Surfaces Airflow import errors if DAG discovery fails.
- Triggers one real Stage 7J monitoring run and waits for SUCCESS during `--execute`.
- Leaves the existing `*/15 * * * *` schedule enabled, so the UI accumulates genuine DQ/CDC/capacity history.
- No BigQuery writes, no CDC offset mutation, no model changes, and no procurement mutation.

Run after extraction:

```powershell
$env:PHARMSTOCK_BQ_PROJECT="pharmstock-ai-bq2-2026"
$env:PHARMSTOCK_BQ_SANDBOX="1"
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest tests\test_stage7j_observability.py -q
.\.venv\Scripts\python.exe scripts\run_stage7j.py --execute
```

Expected acceptance includes:

```text
Airflow control plane: HEALTHY
Airflow DAG discovered: pharmstock_stage7j_health
Airflow history run:    SUCCESS (...)
Airflow schedule:       */15 * * * *
STAGE_7J_STATUS=PASS
```
