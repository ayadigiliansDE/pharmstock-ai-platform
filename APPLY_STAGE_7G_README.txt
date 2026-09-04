PharmStock AI Platform V2 - Stage 7G v0.28.0
================================================

Apply this patch ONLY after Stage 7F v0.27.3 has passed.

Important extraction rule
-------------------------
This ZIP intentionally has NO outer pharmstock-ai-platform-v2 folder.
Extract its contents directly into the existing project root:

D:\Data_Engineer_Work_With_VSCode\Projects\pharmstock-ai-platform-v2

Choose Replace/Overwrite when Windows asks.

Validation
----------
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .

Expected unit-test count for this patch baseline:
353 passed

Run Stage 7G
------------
Keep Docker Desktop running, then:

.\.venv\Scripts\python.exe scripts\run_checkpoint.py 7g

Do NOT rerun Stage 7E or Stage 7F just to start Stage 7G.
The first Spark run may download PostgreSQL JDBC 42.7.13 into the persistent Ivy cache.

Success marker:
STAGE_7G_STATUS=PASS

Normal checkpoint cloud mutation: NO
