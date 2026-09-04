# Stage 7M — Local Run

## Preconditions

Stage 7L must have a persisted `PASS` report and a healthy worker.

## Dry run

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7m.py
```

Expected marker:

```text
STAGE_7M_DRY_RUN_STATUS=PASS
```

## First execution

Do not use `--no-build` on the first Stage 7M run.

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7m.py --execute
```

Expected final markers:

```text
STAGE_7M_API_STATUS=PASS
STAGE_7M_RBAC_STATUS=PASS
STAGE_7M_GOVERNANCE_STATUS=PASS
STAGE_7M_WORKBENCH_STATUS=PASS
STAGE_7M_STATUS=PASS
```

## Workbench

After a successful execution, open:

```text
http://127.0.0.1:8091/workbench
```

Local-development API keys are provided by environment variables. The compose defaults exist only
for local simulation; override them with secrets before exposing the service outside a developer
machine.

## Safety boundary

Stage 7M has no Purchase Order endpoint and the `pharmstock_workbench` database role has no
procurement write privilege.
