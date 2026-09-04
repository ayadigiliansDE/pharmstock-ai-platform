# Stage 5B Environment-Isolated Test Hotfix — v0.17.2

This hotfix isolates the Stage 5A BigQuery DDL contract test from the live
`PHARMSTOCK_BQ_*` environment variables used by Stage 5B cloud deployment.

The production generator intentionally remains environment-aware. The test now
clears project, dataset, and location variables before asserting the default
placeholder DDL, so the test is deterministic even in a CLOUD_READY shell.

No Stage 5B cloud loading semantics changed from v0.17.1.
