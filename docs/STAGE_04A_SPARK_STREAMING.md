# Stage 4A — Spark Structured Streaming Foundation

Stage 4A introduces the analytics streaming engine without moving business rules out of
the domain layer.

## Runtime

- Apache Spark: `4.2.0`
- Docker image: `apache/spark:4.2.0-python3`
- Kafka connector: `org.apache.spark:spark-sql-kafka-0-10_2.13:4.2.0`
- Execution: Docker, local Spark master (`local[*]`)
- Trigger: `AvailableNow`

PySpark is intentionally **not** added to the application's Python 3.14 virtualenv.
The application venv remains small and owns domain/producer/test code; Spark owns its
runtime inside the pinned container.

## Kafka networking

The local Kafka compose file now exposes two advertised listeners:

- `localhost:9092` — Windows host applications and the existing Stage 3 Python clients.
- `kafka:19092` — containers on the Compose network, including Spark.

This avoids advertising `localhost` to Spark, where `localhost` would mean the Spark
container rather than the Kafka container.

## Bronze contract

Spark subscribes to the three business topics:

- `pharmstock.sales.v1`
- `pharmstock.inventory.v1`
- `pharmstock.procurement.v1`

Stage 4A validates only the common event envelope. It checks event identity, known event
type, schema version, topic routing, aggregate/correlation identities, Kafka key,
timezone-aware timestamps and the presence of a JSON-object payload.

Valid records are written to `artifacts/stage4a/bronze/` as Parquet. Invalid records are
written to `artifacts/stage4a/quarantine/` with a `validation_error` and the original raw
JSON preserved.

Event-specific payload semantics remain the responsibility of the domain contracts and a
future Silver layer. Bronze intentionally preserves source truth instead of normalizing it
too early.

## Source identity and retries

The immutable Bronze source identity is:

```text
(topic, partition, offset)
```

Each Spark micro-batch writes to a deterministic `batch_id=...` directory using overwrite.
A retry of the same Spark batch therefore targets the same path. Spark checkpoint state is
stored under `artifacts/stage4a/spark_checkpoint/`.

Stage 4A does **not** deduplicate repeated domain `event_id` values in Bronze. If Kafka
contains two records with the same domain event identity at different offsets, both raw
records are retained. Event-level deduplication belongs in Silver; the durable application
processor from Stage 3C already handles application-side replay safety.

## Checkpoint acceptance

`python scripts/run_checkpoint.py 4a`:

1. publishes 50 validated operational events plus one malformed probe;
2. runs Spark with a clean local Stage 4A checkpoint;
3. verifies Bronze + quarantine accounting and unique Kafka source positions;
4. runs Spark a second time without publishing anything;
5. verifies that the preserved checkpoint consumes zero old records on restart.
