# PharmStock Stage 7K.5 v0.35.2 — Ruff E501 Hotfix

Purpose: fix the single Ruff E501 violation in `ml/stage7k5/worker.py` without changing runtime behavior.

Change:
- Split the heartbeat health error message across two f-strings.
- Store heartbeat status in a local variable for readability.
- No model, feature, retry, healthcheck, Kafka, PostgreSQL, BigQuery, or cloud behavior changes.

Validation performed in the handoff environment:
- Python compile: PASS
- Lines over 100 chars in worker.py: 0
- Stage 7K.5 tests: 17/17 PASS
- Combined Stage 7D/7F/7G/7I/7K/7K.5 regression: 96/96 PASS

After extracting at repository root, run:

```powershell
.\.venv\Scripts\ruff.exe check .
```

Then rerun the 96-test regression before the Stage 7K.5 dry run / execute flow.
