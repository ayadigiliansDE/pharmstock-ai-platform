# Stage 2E — Structured Demand + Unit-Sales Simulation

Stage 2E turns the static Stage 2D inventory snapshot into a time-evolving operational dataset.
It deliberately models **unit demand and fulfillment**, not money. No Egyptian prices or revenue are
invented.

## Flow

```text
Completed Stage 2D dataset (_SUCCESS)
        ↓
Reconstruct branch operating profile
        ↓
Synthetic structured demand
  • branch scale/type
  • opening hours
  • weekday
  • hour of day
  • long-tail product popularity
  • explicitly synthetic seasonality cohort
        ↓
Requested units
        ↓
Available + unexpired batch stock?
        ↓
FEFO fulfillment
        ├── fulfilled units
        ├── partial fulfillment
        └── stockout / lost units
        ↓
Inventory transition + stock movement
        ↓
Reorder threshold crossing
        ↓
Ending inventory + ending batches
```

## Truth boundary

The current drug catalog comes from official U.S. openFDA NDC data and the branch network is a
synthetic Egyptian network. Branch/product mapping is therefore still labeled
`synthetic_cross_market_mapping`.

The Stage 2E demand model is also synthetic. Its time and popularity patterns exist to create a
realistic *statistical simulation* and future forecasting signal; they are not observed Egyptian
patient behavior, pharmacy sales, disease prevalence, or clinical claims about individual drugs.

Stage 2E writes `monetary_values_generated = false` and `pricing_status = not_simulated`.

## Bounded-memory contract

Stage 2E reads one completed Stage 2D branch at a time, simulates the full requested horizon for that
branch, writes the branch's outputs/ending state, and releases it before processing the next branch.
It does not load the complete multi-branch inventory state into memory.

## Outputs

```text
artifacts/stage2e/
├── demand_lines/part-XXXXX.csv
├── batch_allocations/part-XXXXX.csv
├── stock_movements/part-XXXXX.csv
├── reorder_triggers/part-XXXXX.csv
├── ending_inventory/part-XXXXX.csv
├── ending_batches/part-XXXXX.csv
├── daily_branch_kpis.csv
├── demand_manifest.json
└── _SUCCESS
```

`demand_lines` retains requested, fulfilled and lost quantity so later ML can learn **true simulated
demand** rather than only fulfilled sales. This distinction matters because sales alone understate
demand during stockouts.

## Why ending state is persisted

Later replenishment and streaming stages need a continuation point. Stage 2E therefore emits the
post-simulation inventory and batch snapshots instead of leaving the stock transition visible only
inside process memory.
