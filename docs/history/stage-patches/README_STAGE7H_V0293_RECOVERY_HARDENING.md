# Stage 7H v0.29.3 — Recovery + Promotion Hardening

This hotfix addresses the `inventory.stock_movement` promotion failure where all
36 Parquet load jobs completed but the promoted final table contained only
4,373,242 rows instead of the expected 6,844,006.

Changes:
- adds `scripts/repair_stage7h_stock_movement.py` to recover the deleted fully-loaded
  staging table from BigQuery Time Travel using the last successful load job;
- validates recovered rows and duplicate primary keys before touching the partial final;
- recreates the final table with the project's canonical `atomic_replace_sql`;
- validates the final with a real `COUNT(*)` before deleting the recovered staging copy;
- hardens `scripts/run_stage7h_cloud.py` so stage/final row validation uses real COUNT(*);
- preserves a fully validated staging table when promotion fails, preventing another
  expensive re-upload; partial/invalid stages are still cleaned up.

Patch is root-relative. Extract directly into the project root.
