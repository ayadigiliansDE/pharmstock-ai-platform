# Stage 7J v0.31.2 — Airflow Startup Retry Hotfix

Fixes a transient Airflow webserver startup failure where `/health` can close the connection before returning an HTTP response.

Changes:
- Treats `http.client.RemoteDisconnected` and connection-level startup errors as retryable while waiting for Airflow health.
- Extends the Airflow health wait window from 180s to 300s.
- Does not change BigQuery data, CDC offsets, storage policy, DAG schedule, or DQ logic.
- Adds a regression test proving a transient disconnect is retried and then accepted once Airflow is healthy.

Safe recovery command after applying:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7j.py --execute
```

No reset is required.
