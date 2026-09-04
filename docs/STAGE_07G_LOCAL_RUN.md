# Stage 7G — Local Run

## Prerequisites

Stage 7E and Stage 7F must already have passed:

```text
artifacts/stage7e/_SUCCESS
artifacts/stage7f/_SUCCESS
```

Docker Desktop must remain running. Do not rerun Stage 7E or Stage 7F merely to start Stage 7G.

## Run

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 7g
```

The first Stage 7G run may download the PostgreSQL JDBC package into the persistent Spark Ivy
volume. The historical rebuild reads several million rows, so it is intentionally much heavier
than a unit-test checkpoint.

## Expected end state

```text
STAGE_7G_STATUS=PASS
```

Important generated artifacts:

```text
artifacts/stage7g/history/...
artifacts/stage7g/cdc_catchup/...
artifacts/stage7g/reconciled/...        # only tables changed during cutover
artifacts/stage7g/cutover_start_offsets.json
artifacts/stage7g/cutover_end_offsets.json
artifacts/stage7g/cdc_resume_offsets.json
artifacts/stage7g/bigquery_rebuild_plan.json
artifacts/stage7g/rebuild_verification.json
```

No Google Cloud resource is mutated by this checkpoint.
