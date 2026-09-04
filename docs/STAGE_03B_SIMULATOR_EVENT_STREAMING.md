# Stage 3B — Simulator Event Streaming

## Goal

Stage 3A proved one validated event could travel through Kafka. Stage 3B connects the
completed operational simulator outputs to the three business Kafka topics.

This stage intentionally uses a **deterministic artifact-replay bridge**:

```text
Stage 2E / Stage 2F.1 validated artifacts
        -> versioned domain events
        -> Kafka producer batches
        -> sales / inventory / procurement topics
        -> consumer validation
```

It does not yet publish inline while the simulator transaction is executing. That later
outbox/live-publication step should reuse the same event contracts rather than changing
business rules.

## Event contracts added

- `sale.units_fulfilled` — physical fulfilled units only; no price/revenue.
- `inventory.quantity_changed` — sale/restock quantity transition.
- `inventory.reorder_required` — existing V1 reorder contract.
- `purchase_order.created` — physical PO summary; no money.
- `goods_receipt.received` — physical receipt summary.
- `restock.applied` — received units applied to one branch-product inventory item.

## Truth boundary

The stage preserves all prior simulation labels:

- demand remains synthetic,
- supplier identities/service metrics remain synthetic,
- the current US-catalog / Egyptian-network mapping remains synthetic,
- no prices, costs, revenue or profit are generated.

## Replay identity

Every replay event gets a deterministic UUID5 `event_id` derived from the source artifact
identity. Replaying the same completed simulator window therefore generates the same event IDs.
This enables downstream deduplication when replay becomes necessary.

## Ordering / trace context

- Sale -> inventory change -> reorder keeps a causal chain through `causation_id`.
- Purchase order -> goods receipt -> restock -> inventory change does the same.
- Branch-product inventory events share a deterministic aggregate ID, which becomes the Kafka key.
- Kafka preserves ordering for a key inside a partition.

## DLQ

Stage 3B adds a dedicated dead-letter producer using `pharmstock.dead-letter.v1`.
Validated Stage 2E/2F.1 artifacts are expected to produce zero DLQ records in the checkpoint.
A future streaming consumer will use this path for malformed/unsupported incoming records.

## Scale behavior

`KafkaEventProducer.publish_many()` sends bounded batches and flushes once per batch instead of
flushing once per event. The artifact bridge also operates partition-by-partition rather than
loading the entire simulation into memory.

The offline reference acceptance produced 83,132 unique events from the large Stage 2E/2F.1
reference artifacts with zero duplicate event IDs and zero dead letters.
