# Stage 7K.5 v0.35.1 — Online Decision Runtime

This patch turns accepted Stage 7K champions into an operational CDC-triggered inference path.

Key controls:

- PostgreSQL read-through features prevent no-data CDC cold-start corruption.
- Four champion models are invoked only for affected entities.
- PostgreSQL `mlops` journal + transactional outbox provide durable prediction handoff.
- Kafka source offsets are committed after durable decision persistence and output publish.
- Deterministic prediction IDs support downstream deduplication; cross-system exactly-once is not claimed.
- Stockout alerts use model-threshold-relative severity and six-hour duplicate cooldown.
- Five local ML Kafka output topics expose demand, stockout, reorder, expiry and model events.
- The ML operational schema is blocked from the Debezium publication.
- No BigQuery write and no cloud mutation are performed.

See `docs/STAGE7K5_STREAMING_ML_DESIGN.md` and `docs/STAGE_07K5_LOCAL_RUN.md`.
