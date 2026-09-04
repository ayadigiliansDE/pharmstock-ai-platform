# Stage 4A — Local Windows / PowerShell Run

Run all commands from the project root.

## 1. Install the checkpoint

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -c "import pharmstock; print(pharmstock.__version__)"
```

Expected version:

```text
0.14.0
```

## 2. Source quality

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
```

Expected test target:

```text
162 passed
All checks passed!
```

## 3. Recreate local Kafka with host + Docker listeners

Stage 4A changes only the disposable local Kafka networking configuration. Recreate the
broker so Spark can reach it by the internal listener `kafka:19092` while Windows clients
continue to use `localhost:9092`.

```powershell
docker compose -f infra/docker/docker-compose.kafka.yml up -d --force-recreate
docker compose -f infra/docker/docker-compose.kafka.yml ps
```

Expected status:

```text
pharmstock-kafka ... Up ... (healthy)
```

The local Kafka broker has no persistent volume by design, so recreating it resets the
local topics. The Stage 4A checkpoint recreates managed topics and publishes its own probe.

## 4. Run the visible Spark checkpoint

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 4a
```

The first run pulls the pinned Spark image and the pinned Kafka connector if they are not
already cached locally.

With a freshly recreated broker, the important acceptance shape is:

```text
Published Stage 4A probe: 50 valid + 1 malformed

Spark pass 1:
  new input rows      = 51
  Bronze rows         = 50
  quarantine rows     = 1

Spark pass 2:
  new input rows      = 0

STAGE_4A_STATUS=PASS
```

If other business-topic messages were published after broker recreation, the first-pass
counts can be higher. The hard requirements are: at least the 51 probe records are seen,
at least one quarantine row exists, the second pass reads zero old offsets, and duplicate
Kafka source positions remain zero.

## 5. Inspect the generated files

```text
artifacts\stage4a\bronze\
artifacts\stage4a\quarantine\
artifacts\stage4a\batch_metrics\
artifacts\stage4a\spark_checkpoint\
artifacts\stage4a\first_pass_summary.json
artifacts\stage4a\second_pass_summary.json
artifacts\stage4a\checkpoint_verification.json
artifacts\stage4a\_SUCCESS
```

Bronze and quarantine are Parquet datasets. Later stages will query them through Spark and
warehouse tooling rather than treating Parquet files as the final BI interface.

## 6. Run one additional Spark pass without resetting the checkpoint

```powershell
.\.venv\Scripts\python.exe scripts\run_stage4a_spark.py
```

If no new Kafka records exist, `new_input_rows` should remain zero. Publish new Stage 3B
records first if you want to watch the Bronze dataset grow.
