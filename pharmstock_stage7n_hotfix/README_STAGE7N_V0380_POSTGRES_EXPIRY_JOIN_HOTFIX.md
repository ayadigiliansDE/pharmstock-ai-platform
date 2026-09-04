# PharmStock Stage 7N v0.38.0 — PostgreSQL Expiry BI Join Hotfix

## Root cause
`bi.v_ml_expiry_risk` joined `inventory.stock_batch` and then used
`USING (branch_id)` / `USING (product_id)`. After the stock-batch join, the
left relation contained duplicate columns with those names, so PostgreSQL
raised:

`common column name "branch_id" appears more than once in left table`

## Fix
The expiry BI view now uses explicit qualified `ON` predicates:

- `ose.source_event_id = r.source_event_id`
- `sb.batch_id = r.batch_id`
- `sb.branch_id = r.branch_id`
- `sb.product_id = r.product_id`
- `b.branch_id = r.branch_id`
- `p.product_id = r.product_id`

This preserves the batch/branch/product integrity and removes ambiguous
`USING` joins. No data is modified and no BigQuery definition is changed.

## Validation
- Stage 7N tests: 16 passed
- Full regression: 155 passed
- Python compile: PASS

Run locally:

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest tests\test_stage7n_powerbi_prod.py -q
.\.venv\Scripts\python.exe scripts\run_stage7n_powerbi.py --execute
```
