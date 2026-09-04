# Stage 7K.5 v0.35.2 — Runtime Reliability Hardening

This patch hardens the already accepted v0.35.1 online decision runtime without changing model training, feature definitions, champion selection, prediction semantics, BigQuery state, or cloud resources.

## Added reliability controls

- Real Docker healthcheck for the continuous Stage 7K.5 worker.
- Health requires a fresh worker heartbeat, PostgreSQL reachability, all ML output Kafka topics, all four Stage 7K production champions, and prediction-outbox count/age inside configured SLOs.
- Malformed CDC envelopes are durably quarantined in `mlops.online_source_quarantine` before their Kafka source offset is committed. This prevents poison-message restart loops while preserving the raw bad payload for audit/recovery.
- Valid CDC events are never skipped because of model/API/database processing failures. Their source offsets remain uncommitted and processing retries with bounded exponential backoff.
- Heartbeats now expose quarantine count, retry attempt, pending outbox, oldest pending age, and maximum publish attempts.
- The launcher waits for Docker `healthy`, not only a heartbeat file, before declaring Stage 7K.5 PASS.

## Safety boundary

- No Stage 7K retraining.
- No historical CDC replay.
- No BigQuery writes.
- No cloud mutation.
- No automated purchase-order creation.
- `mlops` remains excluded from the Debezium publication.

## Validation

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

Expected regression count for this patch: `96 passed`.

Then run:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7k5.py
.\.venv\Scripts\python.exe scripts\run_stage7k5.py --execute
```

Do not use `--no-build` on the first v0.35.2 execution because the worker image tag and healthcheck changed.
