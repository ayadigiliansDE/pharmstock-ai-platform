# PharmStock Stage 7H v0.29.5 — BigQuery Sandbox-safe recovery

## Root cause fixed

The project is running in BigQuery Sandbox. Sandbox enforces a 60-day lifetime
for tables and partitions. Stage 7H production layouts partition several raw
facts by their historical event date. Historical partitions older than 60 days
were therefore expiring during promotion, causing row-count loss such as:

- `inventory.stock_movement` expected: `6,844,006`
- partial final observed: `3,989,621`
- preserved recovered staging: `6,844,006`

Trying to set dataset/table expiration to `NULL` is rejected in Sandbox with a
403 billing error. v0.29.5 does not try to disable the Sandbox TTL.

## Sandbox physical-layout fallback

For the zero-billing Sandbox deployment:

- raw Stage 7H finals are materialized **unpartitioned**;
- production clustering is retained;
- the intended production partition expressions remain preserved in code and
  execution metadata;
- the Sandbox 60-day whole-table TTL remains in place.

This preserves the full one-year historical snapshot during the table lifetime
instead of losing old date partitions immediately.

A billing-enabled production deployment can continue to use the original
partitioned physical design.

## Recovery behavior

`scripts/repair_stage7h_expiration.py` now:

1. detects the 60-day Sandbox policy;
2. audits all 26 raw finals with real `COUNT(*)`;
3. keeps already-complete unpartitioned finals;
4. repacks any still-complete partitioned final as unpartitioned;
5. recovers incomplete/missing tables from an existing recovery table or
   BigQuery Time Travel of deleted Stage 7H staging tables;
6. validates row count and duplicate primary keys before promotion;
7. preserves recovery data if promotion fails;
8. reports only tables that still require local Parquet upload.

`run_stage7h_cloud.py` now auto-detects Sandbox and uses the same unpartitioned
raw-final layout for any remaining uploads, so the issue cannot recur on tables
22–26.

## Install

Extract this ZIP directly into the project root and replace existing files.
There is no outer project folder in the patch.

## Validate

```powershell
.\.venv\Scripts\ruff.exe check scripts\run_stage7h_cloud.py scripts\repair_stage7h_expiration.py src\pharmstock\rebuild\bigquery_stage.py tests\test_stage7h_sandbox_layout.py

.\.venv\Scripts\python.exe -m pytest tests\test_stage7h_bigquery_dbt.py tests\test_stage7h_sandbox_layout.py -q
```

## Recover first

Do **not** start the normal Stage 7H run before recovery.

```powershell
$env:PHARMSTOCK_BQ_PROJECT="pharmstock-ai-platform-2026"
$env:PHARMSTOCK_BQ_SANDBOX="1"

.\.venv\Scripts\python.exe scripts\repair_stage7h_expiration.py
```

Target outcome:

```text
RAW_FINALS_READY=26/26
SANDBOX_RAW_LAYOUT=UNPARTITIONED_CLUSTERED
STAGE7H_SANDBOX_RECOVERY_STATUS=PASS
```

If the result is `PARTIAL`, only the listed `Need local upload` tables need to
be uploaded by the normal Stage 7H runner.

## Resume Stage 7H after recovery

```powershell
$env:PHARMSTOCK_BQ_PROJECT="pharmstock-ai-platform-2026"
$env:PHARMSTOCK_BQ_SANDBOX="1"

.\.venv\Scripts\python.exe scripts\run_stage7h_cloud.py --execute --replace
```

Do not use `--force-reload`.
