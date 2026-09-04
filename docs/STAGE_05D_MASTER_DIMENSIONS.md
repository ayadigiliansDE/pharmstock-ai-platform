# Stage 5D — Master Data Warehouse Dimensions

Stage 5D adds governed master data to the BigQuery warehouse without inventing market facts.

## Truth boundary

- Product attributes come from the Stage 2B official U.S. openFDA NDC catalog.
- Pharmacy organizations and branches are synthetic Egyptian simulation entities.
- Suppliers are synthetic entities from Stage 2F.1.
- No price, revenue, cost, or margin is generated.

## Flow

```text
Stage 2B product catalog + Stage 2D network identity + Stage 2F.1 supplier master
        ↓
local Stage 5D snapshot + lineage validation
        ↓
pharmstock_master BigQuery dataset
        ↓
dbt master staging views
        ↓
dim_product + dim_branch + dim_supplier
        ↓
relationship tests against Stage 5C facts/marts
        ↓
Power BI-ready dimensional layer
```

The branch network is reconstructed with the exact Stage 2D seed and branch count so identifiers
match the operational simulation that eventually produced the BigQuery Silver/Gold facts.
