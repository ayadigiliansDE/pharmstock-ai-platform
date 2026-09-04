# PharmStock Stage 7K.5 v0.35.2 Serving Readiness Hotfix

## Root cause
`run_stage7k5.py --execute` force-recreated Stage 7K model-serving and then relied on incidental elapsed build time before running the Stage 7K.5 bootstrap. With a cached Stage 7K.5 image, the build completed in only a few seconds and bootstrap could reach `http://model-serving:8090/health` while the serving container was only `Started`, not yet `healthy`.

## Fix
- Generalize `_wait_container_health()` so it can wait on a named container.
- After force-recreating `pharmstock-stage7k-serving`, explicitly wait for Docker health status `healthy` (up to 180 seconds).
- Only then continue to schema application, Stage 7K.5 build/bootstrap/smoke.
- Preserve the existing Stage 7K.5 worker health wait before final PASS.

This changes startup orchestration only. No model, feature, CDC, Kafka delivery, PostgreSQL decision-store, or BigQuery behavior is changed.

## Validation
- Stage 7K.5 tests: 17/17 PASS
- Full selected regression: 96/96 PASS
- Python compile: PASS
- Ruff was not available in the patch-build environment; run the repository `.venv` Ruff gate locally.

## Apply
Extract at the repository root and overwrite the two files in `scripts/` and `tests/`.
