PharmStock AI Platform V2 — Stage 7K.5 v0.35.1 Online Decision Runtime

Prerequisite
------------
Stage 7F must already PASS with 14 CDC topics including:
  pharmstock.ops.pos.demand_attempt
Stage 7K must already PASS with 4/4 production-ready champions.

Apply
-----
Extract this ZIP into the project root and overwrite matching files.

Validate
--------
.\.venv\Scripts\ruff.exe check .

.\.venv\Scripts\python.exe -m pytest `
tests\test_onprem_postgres_contract.py `
tests\test_stage7f_cdc.py `
tests\test_stage7g_rebuild.py `
tests\test_stage7i_cdc.py `
tests\test_stage7k_ml.py `
tests\test_stage7k5_online.py -q

Expected targeted regression: 92 passed.

Dry run
-------
.\.venv\Scripts\python.exe scripts\run_stage7k5.py

Expected:
  STAGE_7K5_DRY_RUN_STATUS=PASS

First execution
---------------
.\.venv\Scripts\python.exe scripts\run_stage7k5.py --execute

Do NOT use --no-build on the first execution because the new Stage 7K.5 worker image must be built.

Expected final markers:
  STAGE_7K5_BOOTSTRAP_STATUS=PASS
  STAGE_7K5_SMOKE_STATUS=PASS
  STAGE_7K5_WORKER_STATUS=PASS
  STAGE_7K5_STATUS=PASS

Later executions may use:
.\.venv\Scripts\python.exe scripts\run_stage7k5.py --execute --no-build

Safety boundary
---------------
- No BigQuery writes.
- No cloud mutation.
- No historical CDC replay.
- No Stage 7K retraining.
- ML output tables are blocked from the Debezium source publication.
