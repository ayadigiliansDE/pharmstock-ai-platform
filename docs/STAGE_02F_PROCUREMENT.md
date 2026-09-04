# Stage 2F — Procurement & Replenishment

Stage 2F closes the first physical inventory loop after the completed Stage 2E demand week.

## What this stage adds

```text
Stage 2E ending inventory
        +
Reorder state / lineage
        ↓
End-of-cycle procurement run
        ↓
Synthetic supplier assignment
        ↓
Purchase Orders
        ↓
Synthetic lead time
        ↓
Goods Receipts
        ↓
Restock movements + new batches
        ↓
Final inventory / batch ledger
```

## Timing rule

Stage 2F starts **after** the Stage 2E demand window. It does not inject deliveries back into
the already-completed historical Stage 2E week. This preserves temporal consistency and keeps
the Stage 2E reconciliation valid. A later long-horizon simulator can interleave sales and
procurement events on one shared clock.

## Truth boundary

Supplier identities, regional assignments and lead times are **synthetic**. They are not real
Egyptian pharmaceutical distributors or measured service-level data. Stage 2F still generates
no prices, costs, revenue or profit.

## Capacity rule

For each branch:

```text
final physical units <= storage_capacity_units
```

If restoring every low-stock product to its target would exceed physical branch capacity, the
engine orders only what fits and writes the remainder to `procurement_backlog.csv` with the
reason `storage_capacity_limit`.

## Reconciliation rules

The stage enforces:

```text
Stage 2E ending units + received units = Stage 2F final units
ordered units = received units                 # current default service-level policy
sum(restock movement deltas) = received units
sum(final batch quantities) = final inventory units
```

## Important files

- `src/pharmstock/domain/procurement.py` — Supplier, PO and Goods Receipt contracts
- `src/pharmstock/simulation/procurement.py` — end-of-cycle procurement engine
- `scripts/run_stage2f_procurement.py` — visible local runner
- `tests/test_procurement_domain.py` — procurement-domain tests
- `tests/test_procurement_simulation.py` — reconciliation/capacity/integration tests
