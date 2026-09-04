# Stage 7I v0.30.2 — BigQuery current-state view SQL hotfix

Fixes the Stage 7I probe failure:

`400 Syntax error: Unexpected keyword PARTITION`

Root cause: the CDC event-table columns named `partition` and `offset` were emitted unquoted in the `ROW_NUMBER() ... ORDER BY` clause. Both are now quoted as BigQuery identifiers:

```sql
ORDER BY COALESCE(source_lsn, -1) DESC, `partition` DESC, `offset` DESC
```

Safety / recovery behavior:
- No reset.
- No raw-table rewrite.
- No historical reload.
- No CDC offsets were advanced by the failed probe because the failure happened before the Spark batch/load/offset-commit path.
- The 3 probe events already in Kafka are intentionally left pending and will be consumed by the next successful run.
- Existing empty delta table / partially-created current-state views are safe to reuse; views are `CREATE OR REPLACE VIEW`.

Patch files:
- `src/pharmstock/cdc/stage7i.py`
- `tests/test_stage7i_cdc.py`
