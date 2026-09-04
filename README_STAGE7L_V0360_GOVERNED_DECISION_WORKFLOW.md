# PharmStock Stage 7L v0.36.0 — Governed Decision Workflow

This patch adds the first operational consumer layer after the accepted Stage 7K.5 online ML
runtime.

## Production boundary

- consumes only stockout, reorder and expiry ML decision topics;
- bootstraps the latest non-smoke Stage 7K.5 prediction journal before continuous consumption;
- uses Kafka committed offsets on restart and the assigned high watermark for a brand-new group;
- persists a durable inbox, malformed-event quarantine, decision cases, model evidence and audit;
- creates a replenishment **draft** for actionable reorder recommendations;
- requires a human transition before a draft can reach `APPROVED_DRAFT`;
- never selects a supplier automatically;
- never writes a Purchase Order or Goods Receipt;
- runs with dedicated PostgreSQL role `pharmstock_decision`, whose procurement writes are revoked;
- ignores Stage 7K.5 acceptance-smoke events as operational work;
- performs the Stage 7L governance smoke inside a transaction and rolls it back.

## Validation performed in the handoff environment

```text
Stage 7L contract tests: 14/14 PASS
Regression chain:        111/111 PASS
Python compile:          PASS
Line-length check:       PASS / 0 violations > 100 chars in new Python files
```

Ruff is not installed in the handoff runtime. Run the repository-pinned Ruff from `.venv` before
execution.

## First local acceptance

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

.\.venv\Scripts\python.exe scripts\run_stage7l.py
```

Do not run `--execute` until Ruff, the 111-test regression and the Stage 7L dry run all pass.
