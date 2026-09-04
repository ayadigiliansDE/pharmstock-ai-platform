# Stage 7M — Operational Decision API + Pharmacy Workbench

## Goal

Expose Stage 7L governed decision cases through a stable, least-privilege HTTP boundary for human
pharmacy operations. Stage 7M deliberately stops before supplier selection, Purchase Order creation,
or Goods Receipt execution.

## Runtime

- FastAPI service bound to `127.0.0.1:8091`.
- Browser workbench at `/workbench`.
- API-key RBAC with `viewer`, `operator`, `manager`, and `admin` roles.
- PostgreSQL login `pharmstock_workbench` with column-scoped workflow updates.
- Stage 7L remains the case creator and ML-event consumer.

## API contract

- `GET /health`
- `GET /v1/meta`
- `GET /v1/metrics/summary`
- `GET /v1/cases`
- `GET /v1/cases/{case_id}`
- `POST /v1/cases/{case_id}/actions`
- `GET /workbench`

There is no supplier-selection, Purchase Order, receiving, or procurement-execution endpoint.

## RBAC

- `viewer`: read-only.
- `operator`: acknowledge and close.
- `manager`: operator actions plus reject and approve replenishment draft.
- `admin`: all Stage 7M workflow actions, still with no procurement execution privilege.

Actor identity is derived from the configured API key. The client cannot supply an arbitrary actor
or role header.

## Database safety

`pharmstock_workbench` can read the governed workbench view and supporting decision evidence. It can
update only workflow-state columns and append to the audit log. It cannot create/delete decision
cases, alter model evidence, write ML inbox/quarantine data, or write any procurement execution
table.

Stage 7M additionally revokes `UPDATE` and `DELETE` on `decision_ops.decision_audit` from operational
roles, making the workflow audit append-only at the permission boundary.

## Power BI / AI boundary

The stable `decision_ops.v_case_workbench` read model and `/v1/metrics/summary` contract are intended
as the governed operational source for the upcoming Power BI serving extension and AI Assistant.
Neither consumer should write directly to PostgreSQL procurement tables.

## Cloud safety

Stage 7M is local-only. It performs no BigQuery write and no cloud mutation.
