PharmStock AI Platform V2 — Stage 7F patch v0.27.0
===================================================

Purpose
-------
Adds Stage 7F: PostgreSQL logical WAL -> Debezium CDC -> Kafka.

Important design boundary
-------------------------
Stage 7F uses snapshot.mode=no_data so it does NOT replay the million-scale Stage 7E history
through Kafka. Stage 7G will own the controlled historical Spark/BigQuery rebuild while Stage 7F
owns new operational CDC changes.

Apply on Windows
----------------
1) Put this ZIP in:
   D:\Data_Engineer_Work_With_VSCode\Projects

2) Open PowerShell in that Projects folder.

3) Apply/overwrite the patch:
   Expand-Archive -Path .\pharmstock-ai-platform-v2-stage7f-v0.27.0-patch.zip -DestinationPath . -Force

4) Enter the project:
   cd .\pharmstock-ai-platform-v2

5) Refresh editable install:
   .\.venv\Scripts\python.exe -m pip install -e ".[dev]"

6) Regression tests:
   .\.venv\Scripts\python.exe -m pytest -q

7) Ruff:
   .\.venv\Scripts\ruff.exe check .

8) Make sure Docker Desktop is running, then run Stage 7F:
   .\.venv\Scripts\python.exe scripts\run_checkpoint.py 7f

Expected final line
-------------------
STAGE_7F_STATUS=PASS

Generated acceptance artifacts
------------------------------
artifacts\stage7f\cdc_contract.json
artifacts\stage7f\connector_config_redacted.json
artifacts\stage7f\cdc_verification.json
artifacts\stage7f\_SUCCESS
