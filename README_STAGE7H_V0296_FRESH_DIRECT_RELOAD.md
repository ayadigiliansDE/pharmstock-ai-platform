# Stage 7H v0.29.6 — Sandbox Fresh Direct Reload

Purpose: stop spending time on Time Travel/repack recovery after BigQuery Sandbox free-storage quota failures.

This patch adds `scripts/run_stage7h_sandbox_fresh.py`.

## Key behavior

- Uses the already-built Stage 7G Parquet snapshot. **Do not rerun Stage 7G.**
- Optional one-time `--reset` deletes only the Stage 7H raw/rebuild dbt datasets in BigQuery.
- Loads each of the 26 raw tables **directly into its final BigQuery table**.
- No `__stage7h_*` temporary copy and no promotion copy.
- Sandbox physical layout is **UNPARTITIONED + CLUSTERED** so historical rows are not immediately removed by the forced 60-day partition TTL.
- Production partition expressions stay preserved in `TABLE_LAYOUTS`/project metadata.
- Row count and duplicate-primary-key validation run after every table.
- Resume-safe: if interrupted, rerun without `--reset`; complete valid finals are skipped and only the current incomplete table is reloaded.
- Soft storage safety stop at 9.25 GiB before starting another table.

## First clean run

```powershell
$env:PHARMSTOCK_BQ_PROJECT="pharmstock-ai-platform-2026"
$env:PHARMSTOCK_BQ_SANDBOX="1"

.\.venv\Scripts\python.exe scripts\run_stage7h_sandbox_fresh.py --execute --reset
```

## Resume after interruption

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7h_sandbox_fresh.py --execute
```

## After raw PASS

When this appears:

```text
STAGE_7H_SANDBOX_RAW_STATUS=PASS
```

run:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7h_cloud.py --execute --replace
```

The existing Stage 7H runner should recognize all 26 unpartitioned raw finals as valid, skip re-upload, and proceed to dbt.
