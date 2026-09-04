# Stage 4B — Silver Parsing, Deduplication and Normalization

Stage 4B transforms the source-faithful Stage 4A Bronze Parquet dataset into clean,
event-specific Silver facts.

## Why Silver exists

Bronze intentionally keeps every Kafka source position, including valid replay copies of the
same domain `event_id`. Silver is where the platform applies event identity and payload
semantics:

```text
Bronze Kafka positions
        |
        +--> same event_id + same semantic content -> keep one canonical row
        |                                      \--> exact_duplicates audit
        |
        +--> same event_id + different semantic content -> conflict audit, keep none
        |
        +--> unique event_id + invalid V1 payload -> payload_rejects audit
        |
        \--> unique valid event -> event-specific Silver table
```

`recorded_at` is excluded from the semantic equality hash because artifact replay may observe
the same immutable domain event at a different publication/recording time. Event identity,
event type, schema, aggregate identity, occurrence time, correlation/causation and payload are
still protected.

## Silver tables

- `sales_units_fulfilled`
- `inventory_quantity_changed`
- `inventory_reorder_required`
- `purchase_order_created`
- `goods_receipt_received`
- `restock_applied`
- `event_index` (common lineage/index for valid Silver events)

Every normalized row retains Kafka topic, partition and offset lineage.

## Audit tables

- `audit/exact_duplicates`
- `audit/event_id_conflicts`
- `audit/payload_rejects`

Stage 4B requires complete accounting:

```text
Bronze rows
=
Silver rows
+ exact duplicate rows
+ event-id conflict rows
+ payload reject rows
```

## Local execution mode

The first Silver implementation is a deterministic Spark full refresh over local Bronze
Parquet. This keeps the learning checkpoint inspectable and reproducible. BigQuery/dbt stages
will later replace local full-refresh persistence with warehouse-native incremental/merge
patterns without changing the event contracts.
