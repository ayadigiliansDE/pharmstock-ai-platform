# PharmStock Stage 7K.5 v0.35.1 Ruff Hotfix

This hotfix fixes two lint regressions in `ml/stage7k5/worker.py` without changing the Stage 7K.5 external contract or decision semantics.

## Fixes

1. Ruff I001: reordered the imported symbols from `pharmstock.ml.stage7k5` using Ruff/isort-compatible ordering.
2. Ruff B023: removed the Kafka delivery callback closure over per-loop variables and replaced it with an isolated `_KafkaDeliveryTracker` object per outbox row.

## Safety

- No database schema changes.
- No Kafka topic changes.
- No BigQuery or cloud writes.
- No change to source-offset commit ordering.
- No change to transactional outbox semantics.
- No change to model inference logic or thresholds.

## Validation performed on handoff repository

- Python compile: PASS
- Stage 7F/7G/7I/7K/7K.5 regression suite: 92 passed

Run locally after applying:

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
