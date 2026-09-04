# Stage 3C — Windows / PowerShell Local Run

## 1. Install the checkpoint

```powershell
pip install -e ".[dev]"
python -c "import pharmstock; print(pharmstock.__version__)"
```

Expected version:

```text
0.13.0
```

If PowerShell activation is inconvenient, use the venv Python directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

## 2. Regression and static checks

```powershell
pytest
ruff check .
```

Expected:

```text
150 passed
All checks passed!
```

## 3. Verify Kafka is healthy

```powershell
docker compose -f infra/docker/docker-compose.kafka.yml ps
```

Expected: `pharmstock-kafka` is `healthy`.

If stopped:

```powershell
docker compose -f infra/docker/docker-compose.kafka.yml up -d
```

## 4. Run the deterministic Stage 3C checkpoint

Stage 2E and Stage 2F.1 artifacts must already exist.

```powershell
python scripts\run_checkpoint.py 3c
```

The checkpoint does all of the following after both Kafka consumers have partition assignments:

- selects 50 deterministic Stage 2E events;
- selects 50 deterministic Stage 2F.1 events;
- publishes those 100 valid event IDs twice;
- publishes one additional valid event whose checkpoint handler intentionally fails;
- publishes one malformed raw message into the inventory topic;
- processes all 202 source messages with a fresh SQLite inbox;
- verifies exactly 100 processed + 100 duplicate + 2 failed outcomes;
- consumes and validates the two new DLQ envelopes.

Expected final section:

```text
Durable processing result:
  Source messages:       202
  Processed:             100
  Duplicates skipped:    100
  Failed -> DLQ:         2

Durable SQLite ledger:
  Unique processed IDs:  100
  Duplicate messages:    100
  Failure records:       2
  DLQ published:         2

STAGE_3C_STATUS=PASS
```

Generated files:

```text
artifacts\stage3c\checkpoint_state.sqlite3
artifacts\stage3c\processing_verification.json
artifacts\stage3c\_SUCCESS
```

## 5. Run a persistent processor manually

Terminal A:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage3c_processor.py `
  --count 200 `
  --group pharmstock-stage3c-worker-001 `
  --state artifacts\stage3c\processor_state.sqlite3
```

After it prints `Waiting for operational events...`, publish events in Terminal B:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage3b_stream.py `
  --stage2e-events 100 `
  --stage2f1-events 100 `
  --batch-size 100
```

The processor state file is persistent. If the same deterministic event IDs are replayed again and consumed by a suitable fresh/repositioned consumer group, the inbox classifies them as duplicates rather than reprocessing them.

## 6. Important consumer-group note

Kafka consumer offsets and application idempotency are separate concepts:

- consumer group offsets decide which Kafka records that group receives;
- the SQLite inbox decides whether an event identity has already been processed.

A new consumer group can reread older Kafka records with `--offset-reset earliest`, while the same persistent SQLite state still prevents duplicate event processing.

## 7. Stop Kafka when finished

```powershell
docker compose -f infra/docker/docker-compose.kafka.yml down
```
