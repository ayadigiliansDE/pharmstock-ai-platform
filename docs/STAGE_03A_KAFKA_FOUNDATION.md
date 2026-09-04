# Stage 3A — Kafka Foundation

## Goal

Move one already-validated PharmStock domain event across a real Kafka broker without moving
business rules into Kafka.

Flow:

`Domain Event -> JSON serializer -> Kafka Producer -> Topic/Partition -> Kafka Consumer -> schema validation`

## Versions

- Apache Kafka `4.3.1` (official JVM Docker image)
- `confluent-kafka==2.15.0`
- Python `>=3.14,<3.15`

## Managed local topics

| Topic | Partitions | Purpose |
|---|---:|---|
| `pharmstock.sales.v1` | 3 | completed sale events |
| `pharmstock.inventory.v1` | 3 | stock changes and reorder events |
| `pharmstock.procurement.v1` | 3 | procurement/restock events |
| `pharmstock.dead-letter.v1` | 1 | future rejected/unprocessable messages |

Local replication factor is 1 because Stage 3A runs one broker. This is **not** the future
production HA policy.

## Contract decisions

- Kafka key = `aggregate_id`, which keeps one aggregate's events on a stable partition.
- Event body = versioned UTF-8 JSON produced from the Pydantic domain event.
- Headers carry event type, schema version, correlation ID, source, and optional causation ID.
- Producer enables idempotence and `acks=all`.
- Consumer validates bytes back into a known Pydantic event before returning them to application code.
- Kafka transports events; it does not decide stock, FEFO, demand, or procurement rules.

## What Stage 3A intentionally does not do

- no Spark yet
- no Schema Registry yet
- no full simulator event flood yet
- no multi-broker production cluster yet
- no SASL/TLS yet; localhost broker is development-only
