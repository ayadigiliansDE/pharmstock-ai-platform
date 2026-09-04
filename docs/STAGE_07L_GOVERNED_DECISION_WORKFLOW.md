# Stage 7L — Governed Operational Decision Workflow

Stage 7L converts Stage 7K.5 ML outputs into reviewable operational work without allowing the
model to create purchase orders or select suppliers automatically.

## Runtime boundary

```text
Stage 7K.5 production-gated ML decisions
        ↓
3 actionable Kafka topics
        ↓
Stage 7L durable inbox + quarantine
        ↓
Decision case + model evidence + audit trail
        ↓
REORDER only: replenishment draft
        ↓
Human acknowledge / approve-draft / reject / close
        ↓
STOP — no supplier selection and no Purchase Order write
```

The three consumed topics are:

- `pharmstock.ml.stockout_predictions`
- `pharmstock.ml.reorder_recommendations`
- `pharmstock.ml.expiry_alerts`

Demand forecasts remain context, not an operational command stream.

## Cold-start policy

A new Stage 7L consumer must not miss decisions created before it starts, and it must not replay
stale compacted-topic history as if every old prediction were current. The worker therefore:

1. joins the Kafka group and captures the assigned high watermark for partitions with no committed
   offset;
2. bootstraps the latest **non-smoke** Stage 7K.5 prediction per logical entity from the durable
   `mlops.prediction_event` journal;
3. resumes Kafka from existing committed offsets, or from the captured high watermark for a new
   group.

Events arriving after the captured watermark remain in Kafka while the database bootstrap runs.

## Governance boundary

Stage 7L creates the dedicated PostgreSQL role `pharmstock_decision`. It can read the Stage 7K.5
prediction journal and write only the `decision_ops` workflow schema. The schema explicitly revokes
INSERT/UPDATE/DELETE on purchase orders and goods receipts.

The accepted reorder lifecycle is:

```text
OPEN -> ACKNOWLEDGED -> APPROVED_DRAFT
```

`APPROVED_DRAFT` is still not a purchase order. Supplier selection is disabled and automatic PO
creation is blocked.

## Model clearing behavior

If a later model event becomes non-actionable:

- OPEN or ACKNOWLEDGED cases close with `MODEL_CLEARED`;
- APPROVED_DRAFT is not silently cancelled, because a human decision already exists.

## Acceptance smoke

The Stage 7L smoke uses a real branch/product reference but performs the workflow lifecycle inside a
single PostgreSQL transaction and rolls the transaction back. It also verifies that the runtime role
has no INSERT/UPDATE privilege on `procurement.purchase_order`.

Stage 7K.5 acceptance-smoke Kafka messages are durably recorded as ignored and never create live
operational cases.
