# Stage 7I v0.30.4 — BigQuery Reserved Alias Hotfix

This hotfix fixes the batch-verification SQL error:

`400 Syntax error: Unexpected keyword ROWS at [2:28]`

## Root cause

The verification query used `rows` as a column alias:

```sql
SELECT COUNT(*) AS rows, COUNT(DISTINCT event_id) AS unique_events
```

`ROWS` is a reserved BigQuery keyword in this parsing context.

## Fix

The alias is changed to the non-reserved name `row_count`, and the Python result accessor is updated accordingly:

```sql
SELECT COUNT(*) AS row_count, COUNT(DISTINCT event_id) AS unique_events
```

No CDC logic, storage guard, baseline data, views, or offsets are reset.

## Recovery behavior

The prior v0.30.3 run successfully loaded the two Parquet files for batch `621793b0dae10e785c5d`, then failed only during verification. On rerun, deterministic BigQuery job IDs are reused, so those successful load jobs are not appended again. The same 3 Kafka events remain pending until verification passes and offsets are advanced.

## Validation performed

`pytest -q tests/test_stage7i_cdc.py` -> `6 passed`

## Apply

Extract this ZIP directly into:

`D:\Data_Engineer_Work_With_VSCode\Projects\pharmstock-ai-platform-v2`

Then run:

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest tests\test_stage7i_cdc.py -q
.\.venv\Scripts\python.exe scripts\run_stage7i_cdc.py --execute
```

Do NOT run `--probe` again and do NOT reset anything.
