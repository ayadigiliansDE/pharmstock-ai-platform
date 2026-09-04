# Stage 7J v0.31.0 — Airflow + Data Quality + Monitoring

This root-relative patch adds a local Airflow control plane, read-only BigQuery quality gates,
CDC health checks, and storage-safe monitoring evidence.

## Storage safety

- No BigQuery raw copy.
- No BigQuery DML/MERGE.
- No streaming writes.
- Monitoring uses metadata plus two compact aggregate CDC queries.
- PASS below 8.2 GiB; warning/acceptance block at 8.2 GiB; hard stop remains 8.5 GiB.

## Validation performed in the build workspace

- Python compileall: PASS
- Stage 7J unit tests: 4 passed
- Changed Python files audited to <= 100 columns

Run `docs/STAGE_07J_LOCAL_RUN.md` after extraction.
