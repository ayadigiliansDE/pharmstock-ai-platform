# Stage 5C Patch — v0.18.0

Adds a dbt BigQuery analytics layer over the Stage 5B Silver warehouse.

- 7 staging views
- 3 ephemeral intermediate models
- 7 Power BI-ready Gold tables
- source/model/singular data tests
- dbt Power BI exposure/lineage metadata
- local-safe parse checkpoint
- explicit cloud execution wrapper with post-build BigQuery verification
- no fabricated price, cost, revenue, or margin
- full master dimensions intentionally deferred until real master snapshots enter BigQuery
