# Stage 7K.5 v0.35.2 local run

## Prerequisites

- Stage 7F verification is `PASS` with 14 CDC topics including `pos.demand_attempt`.
- Stage 7K has four production-ready champions and a healthy local model-serving API.
- Docker Desktop is running.

## Validation before execution

```powershell
.\.venv\Scripts\ruff.exe check .

.\.venv\Scripts\python.exe -m pytest `
tests\test_onprem_postgres_contract.py `
tests\test_stage7f_cdc.py `
tests\test_stage7g_rebuild.py `
tests\test_stage7i_cdc.py `
tests\test_stage7k_ml.py `
tests\test_stage7k5_online.py -q
```

## Dry run

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7k5.py
```

Dry run performs no runtime mutation.

## First execution

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7k5.py --execute
```

The first execution builds only the small Stage 7K.5 worker image. It does not retrain Stage 7K.
It applies the isolated `mlops` schema, creates five local ML Kafka topics, performs a real-feature
non-destructive inference smoke, and starts the continuous worker.

Expected final markers:

```text
STAGE_7K5_BOOTSTRAP_STATUS=PASS
STAGE_7K5_SMOKE_STATUS=PASS
STAGE_7K5_WORKER_STATUS=PASS
STAGE_7K5_RELIABILITY_STATUS=PASS
STAGE_7K5_STATUS=PASS
```

## Later executions

Once the worker image exists:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7k5.py --execute --no-build
```

## Runtime artifacts

- `artifacts/stage7k5/smoke_report.json`
- `artifacts/stage7k5/worker_heartbeat.json`
- `artifacts/stage7k5/stage7k5_report.json`
- `artifacts/stage7k5/_SUCCESS`

## Safety boundaries

- no historical PostgreSQL replay
- no BigQuery writes
- no cloud mutation
- no model retraining per event
- `mlops` tables are excluded from Debezium publication


## v0.35.2 reliability hardening

- Docker health is now a real dependency-aware healthcheck, not only a launcher heartbeat.
- Malformed CDC envelopes are durably quarantined in `mlops.online_source_quarantine` before their source offset is committed, preventing poison-message restart loops.
- Valid-event processing failures keep their source offset uncommitted and retry with bounded exponential backoff.
- Health fails when the heartbeat is stale or the pending prediction outbox breaches configured count/age SLOs.
- The healthcheck verifies PostgreSQL, Kafka output topics and all four Stage 7K production champions.
