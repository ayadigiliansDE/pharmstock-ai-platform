# Stage 5B Schema Compatibility Hotfix — v0.17.1

This hotfix fixes live BigQuery Parquet loading when Spark physical Parquet nullability differs from the logical BigQuery contract.

- Staging tables use the same types but relax logical `REQUIRED` fields to physical `NULLABLE` so self-describing Parquet can load safely.
- Before promotion, Stage 5B queries staging and rejects any row containing NULL in a logical `REQUIRED` field.
- Final tables are rebuilt atomically with `CREATE OR REPLACE TABLE`, explicit `NOT NULL` columns, date partitioning, and clustering.
- Final metadata is re-applied and validated against the original contract.
- Failed run-scoped staging tables are still cleaned in `finally`.
- Existing successful target tables are guarded for schema/partition/clustering drift before replacement.

The failed v0.17.0 run can be safely retried after applying this patch. The dataset and any empty target table created by the failed run do not need manual deletion.
