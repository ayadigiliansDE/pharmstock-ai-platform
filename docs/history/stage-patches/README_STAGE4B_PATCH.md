# Stage 4B Patch — v0.15.0

This flat patch upgrades the completed Stage 4A v0.14.0 checkpoint to Stage 4B.

Adds:
- Spark Bronze -> Silver normalization.
- `event_id` deduplication with exact-replay audit.
- semantic event conflict detection (same ID, different immutable semantics).
- event-specific payload validation and reject audit.
- six normalized Silver event tables plus `event_index`.
- Stage 4B visible local acceptance checkpoint.

Apply directly to the repository root with Replace/Overwrite.
Do not recreate Kafka between a successful Stage 4A run and the Stage 4B checkpoint.

Run:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
docker compose -f infra/docker/docker-compose.kafka.yml ps
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 4b
```

Expected final marker: `STAGE_4B_STATUS=PASS`.
