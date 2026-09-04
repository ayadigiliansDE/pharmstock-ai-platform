# Stage 7I v0.30.3 — BigQuery Parquet Schema Recovery

This hotfix addresses the first real Stage 7I CDC micro-batch append failure:

- Spark successfully read and validated the 3 pending CDC records.
- Storage guard remained SAFE at ~7.926 GiB.
- BigQuery rejected the Parquet append because the existing `events.event_id` field was REQUIRED while Spark Parquet exposed it as NULLABLE.

## Fix

1. The physical BigQuery CDC delta schema is now NULLABLE for all fields. Semantic requiredness remains enforced by Spark validation before upload.
2. Existing Stage 7I `events` tables created by v0.30.0-v0.30.2 are relaxed from REQUIRED to NULLABLE with a metadata-only schema update. No raw baseline copy and no table reset are performed.
3. Failed deterministic BigQuery load-job IDs are skipped using deterministic retry IDs. Successful prior load jobs are still reused, preserving idempotency.
4. CDC offsets are unchanged until BigQuery batch verification passes.

## Apply

Extract this ZIP directly into the project root:

`D:\Data_Engineer_Work_With_VSCode\Projects\pharmstock-ai-platform-v2`

Then run:

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest tests\test_stage7i_cdc.py -q
.\.venv\Scripts\python.exe scripts\run_stage7i_cdc.py --execute
```

Do NOT run `--probe` again. The original 3 CDC events are still pending because offsets were not advanced.
