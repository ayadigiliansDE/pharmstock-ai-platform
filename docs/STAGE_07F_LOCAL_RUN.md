# Stage 7F — Local Run Guide

Run these commands from the project root on Windows PowerShell.

## 1. Docker Desktop

Docker Desktop must be running. Stage 7F needs the existing PostgreSQL data from Stage 7E plus the
local Kafka broker and Kafka Connect/Debezium.

## 2. Regression checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
```

Both must pass before the live checkpoint.

## 3. Run Stage 7F

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 7f
```

The first run may pull the Debezium container image from Quay.io.

## 4. Expected acceptance result

The checkpoint should finish with:

```text
STAGE_7F_STATUS=PASS
```

The verification section should also show:

```text
PostgreSQL logical CDC:        READY
Debezium connector:            RUNNING
Probe INSERT/UPDATE/DELETE:    c -> u -> d
Probe row cleaned up:          YES
Historical 7E rows replayed:   NO
Cloud mutation:                NO
```

## 5. Inspect generated artifacts

```text
artifacts\stage7f\cdc_contract.json
artifacts\stage7f\connector_config_redacted.json
artifacts\stage7f\cdc_verification.json
artifacts\stage7f\_SUCCESS
```

The connector artifact always redacts the PostgreSQL CDC password.

## 6. Optional runtime inspection

```powershell
docker ps --filter "name=pharmstock-connect"
docker logs --tail 100 pharmstock-connect
```

Kafka Connect REST is exposed locally on port 8083 by default.
