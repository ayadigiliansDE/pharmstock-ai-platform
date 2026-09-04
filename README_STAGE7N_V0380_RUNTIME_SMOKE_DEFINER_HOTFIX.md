# Stage 7N v0.38.0 — Runtime Smoke + BI View Definer Hotfix

## Root cause

The Stage 7N runtime-read verification used one `psql -c` command containing:

```sql
SET ROLE pharmstock_bi;
SELECT * FROM bi.<view> LIMIT 0;
SELECT 'PASS';
RESET ROLE;
```

The verifier then expected the final stdout line to be `PASS`. A successful `RESET ROLE`
can emit command-status output after `PASS`, so a healthy BI view could be reported as failed.
This was a verifier bug, not proof that `v_ml_demand_forecast` itself was unreadable.

## Changes

- Runtime smoke now uses `psql` exit status with `ON_ERROR_STOP=1` instead of parsing `PASS` text.
- Failures include the real PostgreSQL stderr/stdout diagnostic.
- All five `bi.*` views explicitly set `security_invoker = false`.
- All five curated views explicitly pin ownership to `pharmstock_admin`.
- `pharmstock_bi` remains read-only and receives no direct write privilege on operational schemas.
- Existing `v_decision_case` direct read-model fix is retained.

## Validation performed in patch workspace

```text
Stage 7N tests: 20 passed
Python compile: PASS
Static >100-char Python line check: PASS
```

## Apply

Extract this ZIP directly into the repository root and overwrite files.

Then run:

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest tests\test_stage7n_powerbi_prod.py -q
$env:PHARMSTOCK_BQ_PROJECT="pharmstock-ai-bq2-2026"
$env:PHARMSTOCK_BQ_SANDBOX="1"
.\.venv\Scripts\python.exe scripts\run_stage7n_powerbi.py --execute
```

Expected Stage 7N test count after this hotfix: `20 passed`.
