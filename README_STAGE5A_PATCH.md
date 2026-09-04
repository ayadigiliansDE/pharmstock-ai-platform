# PharmStock V2 — Stage 5A Patch (v0.16.0)

Apply this flat patch over the accepted Stage 4B v0.15.0 checkpoint.

Stage 5A adds a cloud-safe BigQuery warehouse foundation:

- seven explicit BigQuery contracts;
- Spark validation of actual Silver Parquet schema/types;
- BigQuery-ready Snappy Parquet with `event_date` materialized in-file;
- deterministic schema JSON, DDL, warehouse catalog and dry-run load plan;
- optional `google-cloud-bigquery==3.43.0` extra;
- an explicit cloud loader that is dry-run unless `--execute --replace` are both provided.

Local acceptance:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 5a
```

Expected final marker:

```text
STAGE_5A_STATUS=PASS
```
