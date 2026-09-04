# Stage 3A — Windows / PowerShell Local Run

## Prerequisite

Docker Desktop must be installed and running.

Check:

```powershell
docker --version
docker compose version
```

## 1. Install the updated Python package

```powershell
pip install -e ".[dev]"
python -c "import pharmstock; print(pharmstock.__version__)"
```

Expected version: `0.11.0`.

## 2. Regression checks

```powershell
pytest
ruff check .
```

## 3. Start Kafka

```powershell
docker compose -f infra/docker/docker-compose.kafka.yml up -d
```

Inspect:

```powershell
docker compose -f infra/docker/docker-compose.kafka.yml ps
```

Wait until the service is healthy. First startup may pull the Kafka image.

## 4. Create/verify topics

```powershell
python scripts/run_stage3a_topics.py
```

Expected: `STAGE_3A_TOPICS_STATUS=PASS`.

## 5. Automated round trip

```powershell
python scripts/run_checkpoint.py 3a
```

Expected: `STAGE_3A_STATUS=PASS` and matching produced/consumed offsets.

## 6. Manual two-terminal learning exercise

Terminal A:

```powershell
python scripts/run_stage3a_consumer.py --count 1 --group pharmstock-learning-001
```

After it prints `Waiting for events...`, keep it open.

Terminal B:

```powershell
python scripts/run_stage3a_producer.py
```

Terminal B should print producer PASS; Terminal A should show the same event type/event ID and
consumer PASS.

Use a new `--group` value if you repeat the exercise and want a clean consumer group.

## 7. Stop Kafka

```powershell
docker compose -f infra/docker/docker-compose.kafka.yml down
```

Kafka in Stage 3A has no persistent volume on purpose: it is a disposable learning/development
broker. Production persistence/HA/security will be designed separately.
