# Stage 7K.5 — CDC-Triggered Online Feature & Inference Layer

## Purpose

Turn Kafka CDC from transport-only infrastructure into an operational pharmacy decision path.

## Production prerequisite — complete demand CDC

`pos.demand_attempt` is the authoritative operational demand signal because it records fulfilled,
partial and out-of-stock attempts. `pos.sale_line` alone is insufficient: fully lost demand can
produce no sale line. Stage 7K.5 therefore requires the 14-topic Stage 7F CDC contract including
`pharmstock.ops.pos.demand_attempt`.

The CDC extension keeps `snapshot.mode=no_data`: Stage 7G/7H own the historical baseline while only
new operational mutations are streamed. Existing Stage 7I resume files are upgraded by starting the
new demand topic at its Kafka low watermark.

## v0.35.2 correctness-first + reliability runtime

A newly added no-data CDC topic cannot reconstruct the previous 7/28-day model windows by itself.
Building online state only from post-migration Kafka events would therefore corrupt early predictions.

Stage 7K.5 v0.35.2 uses a CDC-triggered PostgreSQL read-through design:

1. PostgreSQL operational mutation commits.
2. Debezium emits the CDC envelope to Kafka.
3. The Stage 7K.5 worker consumes only model-relevant CDC topics.
4. The event identifies the affected product or branch/product key.
5. The worker reads the authoritative current PostgreSQL state plus the required historical window.
6. The Stage 7K champion API is called only for affected entities.
7. Decisions are committed to the isolated `mlops` operational store and transactional outbox.
8. Prediction messages are published to dedicated Kafka topics.
9. The source Kafka offset is committed only after durable decision persistence and output publish.
10. Stage 7I continues its independent Spark -> BigQuery analytical ingestion path.

This is intentionally not described as cross-system exactly-once delivery. Deterministic
`prediction_event_id` values provide downstream deduplication if a process failure occurs across the
PostgreSQL/Kafka boundary.

## Prediction topics

- `pharmstock.ml.demand_forecasts`
- `pharmstock.ml.stockout_predictions`
- `pharmstock.ml.reorder_recommendations`
- `pharmstock.ml.expiry_alerts`
- `pharmstock.ml.model_events`

Decision-state topics use keyed compaction so a downstream operational consumer can reconstruct the
latest state efficiently.

## Operational prediction store

The local PostgreSQL `mlops` schema contains:

- source-event idempotency ledger
- prediction journal
- transactional prediction outbox
- latest demand forecast per product
- latest stockout/reorder decision per branch/product
- latest expiry risk per batch
- stockout alert cooldown/severity state

The schema is explicitly rejected if it appears in `pharmstock_cdc_publication`, preventing an ML
prediction feedback loop into the source CDC stream.

## Stockout alert control

Stockout is a rare event, so severity is not classified using arbitrary absolute percentages.
Severity is expressed as a multiple of the champion model's validation-selected operating threshold.
Repeated positive alerts are suppressed for a default six-hour cooldown; severity escalation bypasses
the cooldown. All predictions remain available even when a repeated alert is not actionable.

## Training versus online inference

Models are not retrained per Kafka event.

- Online: feature refresh + champion inference + operational decisions.
- Scheduled: drift checks, backtests, retraining and champion promotion.
- Historical warehouse: durable analytical truth and reproducible training windows.

## Spark boundary

Spark remains the Stage 7I durable CDC -> BigQuery processing engine. A stateful Spark online feature
store can be introduced later if throughput measurements justify it, but it must be bootstrapped from
an accepted historical snapshot before replacing PostgreSQL read-through features. v0.35.1 prioritizes
correct first-day model inputs over architectural complexity.

## Cost policy

Stage 7K.5 is local Docker/PostgreSQL/Kafka only. It creates no Cloud Run, Vertex AI, Pub/Sub,
Dataflow or BigQuery writes.


## v0.35.2 reliability semantics

Malformed CDC records are not allowed to poison a partition indefinitely. The worker durably stores the raw invalid payload, Kafka coordinates and error in `mlops.online_source_quarantine`, then commits that one source offset. Valid CDC records are never skipped on model/API/database processing failure: their offsets remain uncommitted and processing retries with bounded exponential backoff.

Docker health is dependency-aware. A worker is healthy only when its heartbeat is fresh, PostgreSQL is reachable, all ML output topics exist, the Stage 7K serving API still exposes four production-ready champions, and the prediction outbox stays inside configured count/age limits.
