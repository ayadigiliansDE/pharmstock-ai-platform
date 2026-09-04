# Stage 3B — Windows / PowerShell Local Run

## 1. Apply/install the checkpoint

```powershell
pip install -e ".[dev]"
python -c "import pharmstock; print(pharmstock.__version__)"
```

Expected version: `0.12.0`.

## 2. Regression + static checks

```powershell
pytest
ruff check .
```

Expected test target: `142 passed`.

## 3. Keep Kafka running

Stage 3A already created the broker and topics. Verify:

```powershell
docker compose -f infra/docker/docker-compose.kafka.yml ps
```

Expected: `pharmstock-kafka` is `healthy`.

If Kafka is stopped:

```powershell
docker compose -f infra/docker/docker-compose.kafka.yml up -d
```

## 4. Bounded end-to-end checkpoint

Stage 2E and Stage 2F.1 artifacts must already exist.

```powershell
python scripts\run_checkpoint.py 3b
```

The checkpoint publishes 300 Stage 2E event candidates and 200 Stage 2F.1 event candidates,
then consumes the same event IDs from sales, inventory and procurement topics using a unique
consumer group.

Expected final marker:

```text
STAGE_3B_STATUS=PASS
```

Generated verification files:

```text
artifacts\stage3b\stream_manifest.json
artifacts\stage3b\roundtrip_verification.json
artifacts\stage3b\_SUCCESS
```

## 5. Visible two-terminal stream exercise

Terminal A:

```powershell
python scripts\run_stage3b_consumer.py --count 20 --group pharmstock-stage3b-learning-001
```

After it prints `Waiting for operational events...`, keep it open.

Terminal B:

```powershell
python scripts\run_stage3b_stream.py --stage2e-events 100 --stage2f1-events 100 --batch-size 100
```

Terminal A should show real Stage 2E/2F.1 operational event types arriving across the three
business topics.

Use a fresh `--group` value when repeating the exercise with `auto.offset.reset=latest`.

## 6. Full replay

After the bounded checkpoint passes, replay all available Stage 2E + Stage 2F.1 artifacts:

```powershell
python scripts\run_stage3b_stream.py --batch-size 1000 --output artifacts\stage3b-full
```

This can publish tens of thousands of events. It intentionally does not consume them back as a
single checkpoint; use consumers/next streaming stages to process them.

## 7. Stop Kafka when finished

```powershell
docker compose -f infra/docker/docker-compose.kafka.yml down
```
