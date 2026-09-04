# PharmStock Stage 7M v0.37.0 — Operational Decision API + Pharmacy Workbench

Stage 7M exposes the accepted Stage 7L governed decisions through a loopback-only FastAPI service and
browser workbench. It adds API-key RBAC, a stable workbench read model, column-scoped PostgreSQL
permissions, append-only operational audit permissions, health/readiness checks, and a non-mutating
acceptance smoke.

The stage does not select suppliers, create Purchase Orders, receive stock, write BigQuery, or mutate
cloud resources.
