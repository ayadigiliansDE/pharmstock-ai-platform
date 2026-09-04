# Stage 7H v0.29.4 — Expiration Recovery Hardening

Root cause confirmed: `pharmstock_ops_rebuild` had both default table expiration and
default partition expiration set to 5,184,000,000 ms (60 days). Partitioned Stage 7H
final tables inherited the 60-day partition retention and historical partitions could
expire immediately/asynchronously during promotion.

This patch:
- disables dataset-level table and partition expiration for the Stage 7H raw dataset;
- clears table/partition expiration on existing Stage 7H finals;
- verifies existing finals using real `COUNT(*)` queries;
- repairs partial/missing finals from preserved cloud recovery tables when available;
- otherwise attempts to restore the latest complete deleted Stage 7H staging snapshot
  from BigQuery time travel using successful load-job history;
- promotes recovered data one table at a time and deletes recovery copies only after
  verified success;
- hardens `run_stage7h_cloud.py` so future promoted/reused raw tables cannot silently
  inherit the accidental 60-day expiration policy.

Run lint first:

```powershell
.\.venv\Scripts\ruff.exe check scripts\run_stage7h_cloud.py scripts\repair_stage7h_expiration.py
```

Then run cloud-side recovery (no local Parquet upload in this repair step):

```powershell
$env:PHARMSTOCK_BQ_PROJECT="pharmstock-ai-platform-2026"
.\.venv\Scripts\python.exe scripts\repair_stage7h_expiration.py
```

Do not run the normal Stage 7H cloud deployment until this repair prints its summary.
If `STAGE7H_EXPIRATION_RECOVERY_STATUS=PASS`, rerun Stage 7H normally without
`--force-reload`; all 26 raw finals should be reused and the process will proceed to dbt.
If the repair prints `PARTIAL`, only the listed tables still require local upload.
