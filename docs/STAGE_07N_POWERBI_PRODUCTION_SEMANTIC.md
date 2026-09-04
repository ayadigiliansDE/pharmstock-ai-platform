# Stage 7N — Power BI Production Semantic & Serving Layer (v0.38.0)

## Goal

Stage 7N replaces the old pre-rebuild Stage 6A serving boundary with a production-oriented
semantic layer that reflects the current PharmStock architecture after Stages 7H–7M.

It deliberately keeps Power BI read-only and separates historical/cloud analytics from
operational ML/decision state.

```text
BigQuery rebuild/current-state                         PostgreSQL operational state
pharmstock_rebuild_gold                                mlops + decision_ops
pharmstock_ops_current                                           │
        │                                                        │
        ▼                                                        ▼
pharmstock_pbi_prod (9 views)                         bi schema (5 read-only views)
        │                                                        │
        └────────────────────────┬───────────────────────────────┘
                                 ▼
                  Power BI semantic model / reports
```

## BigQuery serving dataset

`pharmstock_pbi_prod`

Stage 7N creates **views only**. No BigQuery data table or raw copy is created.

Views:

- `dim_date`
- `dim_branch`
- `dim_product`
- `dim_supplier`
- `fact_branch_daily_operations`
- `fact_product_daily_performance`
- `fact_supplier_performance`
- `snapshot_inventory_position`
- `snapshot_batch_expiry`

The three historical facts consume the accepted Stage 7H rebuild marts. Current inventory and
batch-expiry views consume Stage 7I current-state views.

## PostgreSQL BI serving schema

Stage 7N creates a dedicated `bi` schema and a `pharmstock_bi` login role.

Views:

- `bi.v_ml_demand_forecast`
- `bi.v_ml_branch_product_decision`
- `bi.v_ml_expiry_risk`
- `bi.v_decision_case`
- `bi.v_decision_audit`

The BI role gets `SELECT` only on the curated `bi` views. It has no direct schema access to
`mlops`, `decision_ops`, `inventory`, `master`, or `procurement`, and no write privileges.

## Power BI model

The generated semantic contract contains 14 tables/views, 16 relationships, 24 explicit DAX
measures, and five report pages:

1. Executive Operations
2. Branch & Demand
3. Inventory & Expiry
4. Supplier & Procurement
5. AI & Decision Operations

Initial Desktop storage mode is Import for both sources. If the report is later published to
Power BI Service, PostgreSQL refresh requires an on-premises data gateway until PostgreSQL is
moved to cloud-managed infrastructure.

## Truth boundary

- Egyptian branch network: `SYNTHETIC_CALIBRATED_EGYPT`
- Retail price: `PUBLIC_MARKET_EGYPT`
- Purchase cost / COGS / margin: `SYNTHETIC_CALIBRATED_MODELED`
- Current Stage 7K ML training: synthetic-calibrated offline backfill until sufficient real
  observed history exists
- Decision workflow: real runtime state of the simulated pharmacy platform

These labels must remain visible in project documentation and must not be described as official
EDA financial or operational data.

## Safety

Dry run performs no cloud or database mutation.

`--execute` requires `PHARMSTOCK_BQ_SANDBOX=1` and refuses to start when the accepted Stage 7J
storage report is at or above 8.2 GiB. BigQuery execution creates metadata-only views; it does not
copy the 31.9M-row history.

Power BI is a read-only consumer. It has no purchase-order, supplier-selection, ML-write, or
decision-write boundary.
