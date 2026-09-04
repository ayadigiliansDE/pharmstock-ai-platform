# PharmStock Stage 7M v0.37.0 — PYTHONPATH Startup Hotfix

## Root cause
The Stage 7M API container mounted the repository at `/workspace`, but did not set
`PYTHONPATH=/workspace:/workspace/src`. Uvicorn could resolve the `operations` package
from `/workspace`, while imports from the src-layout `pharmstock` package could fail at
container startup. Docker therefore reported the API service as unhealthy.

## Fix
- Add `PYTHONPATH: /workspace:/workspace/src` to `stage7m-api` environment.
- Add a regression assertion in `tests/test_stage7m_api.py`.
- No API routes, RBAC rules, database grants, decision workflow, model behavior,
  procurement boundaries, BigQuery behavior, or cloud mutation behavior were changed.

## Validation
- Stage 7M tests: 18/18 PASS
- Full regression: 130/130 PASS
- Python compile: PASS

Run Ruff locally, then rerun Stage 7M `--execute`.
