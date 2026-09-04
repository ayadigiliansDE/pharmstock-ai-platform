PharmStock AI Platform V2 - Stage 7I v0.30.0

Purpose
=======
Continuous PostgreSQL CDC -> Debezium -> Kafka -> Spark micro-batches -> BigQuery,
implemented in a BigQuery Sandbox-safe way.

Critical storage policy
=======================
- Stage 7H raw baseline is NEVER copied or rewritten by Stage 7I.
- BigQuery CDC uses one compact append-only delta table.
- Current state is exposed through 26 zero-storage views.
- Before every cloud batch:
    WARN at 8.2 GiB
    HARD STOP at 8.5 GiB
    Sandbox ceiling remains 10 GiB
- CDC offsets advance ONLY after the BigQuery batch is verified.
- If the storage guard blocks a batch, its local Parquet is preserved and offsets do not move.

Apply
=====
Extract this ZIP directly into:
D:\Data_Engineer_Work_With_VSCode\Projects\pharmstock-ai-platform-v2

The ZIP is root-relative. Do not create an outer project folder.

First validation
================
PowerShell:

$env:PHARMSTOCK_BQ_PROJECT="pharmstock-ai-bq2-2026"
$env:PHARMSTOCK_BQ_SANDBOX="1"

.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest tests\test_stage7i_cdc.py -q
.\.venv\Scripts\python.exe scripts\run_stage7i_cdc.py

The last command is DRY RUN and does not mutate BigQuery.

First Stage 7I initialization / one CDC cycle
=============================================
.\.venv\Scripts\python.exe scripts\run_stage7i_cdc.py --execute

Continuous worker
=================
.\.venv\Scripts\python.exe scripts\run_stage7i_cdc.py --execute --watch --interval 60

Stop the worker with Ctrl+C. Resume is safe because offsets are persisted under
artifacts\stage7i\resume_offsets.json only after BigQuery verification.

NEVER use --reset for Stage 7I. There is no reset option in this runner.
