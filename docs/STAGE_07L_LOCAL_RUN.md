# Stage 7L v0.36.0 local run

## Prerequisites

- Stage 7K.5 v0.35.2 accepted with `STAGE_7K5_STATUS=PASS`.
- Docker Desktop running.

## Validate

```powershell
.\.venv\Scripts\ruff.exe check .

.\.venv\Scripts\python.exe -m pytest `
tests\test_onprem_postgres_contract.py `
tests\test_stage7f_cdc.py `
tests\test_stage7g_rebuild.py `
tests\test_stage7i_cdc.py `
tests\test_stage7k_ml.py `
tests\test_stage7k5_online.py `
tests\test_stage7l_workflow.py -q
```

## Dry run

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7l.py
```

Expected marker:

```text
STAGE_7L_DRY_RUN_STATUS=PASS
```

## First execution

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7l.py --execute
```

Expected final markers:

```text
STAGE_7L_BOOTSTRAP_STATUS=PASS
STAGE_7L_SMOKE_STATUS=PASS
STAGE_7L_WORKER_STATUS=PASS
STAGE_7L_GOVERNANCE_STATUS=PASS
STAGE_7L_STATUS=PASS
```

Later executions can reuse the image:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7l.py --execute --no-build
```

## Operator CLI

List active cases:

```powershell
.\.venv\Scripts\python.exe scripts\manage_stage7l_case.py --list-open
```

Acknowledge a case:

```powershell
.\.venv\Scripts\python.exe scripts\manage_stage7l_case.py `
  --case-id <UUID> --action acknowledge --actor "operator-name" --note "review started"
```

Approve a reorder draft:

```powershell
.\.venv\Scripts\python.exe scripts\manage_stage7l_case.py `
  --case-id <UUID> --action approve-draft --actor "operator-name" `
  --note "quantity reviewed"
```

This action does **not** create a purchase order.
