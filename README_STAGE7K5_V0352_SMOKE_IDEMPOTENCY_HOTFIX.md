# PharmStock Stage 7K.5 v0.35.2 Smoke Idempotency Hotfix

## Root cause
The Stage 7K.5 acceptance smoke inserted every synthetic source event with the same logical source position:
`(__stage7k5_smoke__, partition=0, offset=0)`.
Because `mlops.online_source_event` correctly enforces `UNIQUE(topic, partition_id, offset_value)`, rerunning Stage 7K.5 after a previous successful smoke caused a `UniqueViolation`.

## Fix
- Preserve the database UNIQUE constraint.
- Preserve smoke history and prior operational evidence.
- Generate a unique synthetic smoke offset with `time.time_ns()` for every smoke run.
- Include the unique offset and process id in `source_event_id`.
- Add a regression test that rejects the old fixed offset `(0, 0)` behavior.

No model logic, features, Kafka production topics, PostgreSQL business tables, BigQuery behavior, or cloud resources are changed.

## Validation
- Stage 7K.5 tests: 18/18 PASS
- Full selected regression: 97/97 PASS
- Python compile: PASS
- Modified files have no lines longer than 100 characters

## Apply
Extract this archive at the repository root and overwrite files.

Then run:

```powershell
.\.venv\Scripts\ruff.exe check .
```

```powershell
.\.venv\Scripts\python.exe -m pytest `
tests\test_onprem_postgres_contract.py `
tests\test_stage7f_cdc.py `
tests\test_stage7g_rebuild.py `
tests\test_stage7i_cdc.py `
tests\test_stage7k_ml.py `
tests\test_stage7k5_online.py -q
```

Expected: `97 passed`.

Then rerun:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7k5.py --execute
```

The existing `mlops` rows should remain intact; the new smoke run gets a fresh synthetic source offset.
