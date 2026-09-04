# PharmStock Stage 7L v0.36.0 — Least-Privilege Role Safety Hotfix

## Root cause
Stage 7L intentionally denies the `pharmstock_decision` role `USAGE` on the `procurement` schema. The bootstrap safety check used the text form of `has_table_privilege()` with names such as `procurement.purchase_order`. PostgreSQL must resolve that relation name first, and relation resolution itself fails when the current role cannot use the schema. The safety check therefore failed even though the role was correctly locked down.

## Fix
- Keep the procurement schema inaccessible to the Stage 7L role.
- Resolve procurement schema/table OIDs only through `pg_catalog`.
- Use the OID overloads of `has_schema_privilege()` and `has_table_privilege()`.
- Treat missing procurement objects as a safety failure.
- Do not grant `USAGE`, `INSERT`, `UPDATE`, or `DELETE` on procurement objects.

## Validation
- Stage 7L tests: 15/15 PASS
- Full regression: 112/112 PASS
- Python compile: PASS
- Modified files: no lines over 100 characters

## Apply
Extract this ZIP into the repository root and replace existing files.

Then run:

```powershell
.\.venv\Scripts\ruff.exe check .

.\.venv\Scripts\python.exe -m pytest `
tests\test_onprem_postgres_contract.py `
tests\test_stage7f_cdc.py `
tests\test_stage7g_rebuild.py `
tests\test_stage7i_cdc.py `
tests\test_stage7k_ml.py `
tests\test_stage7k5_online.py `
tests\test_stage7l_workflow.py -q

.\.venv\Scripts\python.exe scripts\run_stage7l.py --execute
```

Expected regression count: `112 passed`.
