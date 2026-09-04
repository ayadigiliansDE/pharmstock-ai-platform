# Stage 5C — dbt Analytics / Gold Layer

Stage 5C transforms the live Stage 5B BigQuery Silver warehouse into governed analytics
models for Power BI. It uses dbt Core + dbt-bigquery and keeps all transformations inside
BigQuery.

## Input

- Project: `PHARMSTOCK_BQ_PROJECT`
- Source dataset: `pharmstock_silver` by default
- Location: `EU` by default
- Authentication: Google Application Default Credentials (ADC)

## dbt datasets

The dbt target base dataset defaults to `pharmstock`. With dbt's standard custom-schema
naming this produces:

- `pharmstock_stg` — staging views
- `pharmstock_gold` — Power BI-ready analytics tables

## Models

### Staging views (7)

- `stg_event_index`
- `stg_sales_units_fulfilled`
- `stg_inventory_quantity_changed`
- `stg_inventory_reorder_required`
- `stg_purchase_order_created`
- `stg_goods_receipt_received`
- `stg_restock_applied`

### Intermediate ephemeral models (3)

- `int_sales_daily_branch_product`
- `int_inventory_daily_branch_product`
- `int_procurement_order_lifecycle`

### Gold tables (7)

- `fct_daily_sales_demand`
- `fct_daily_inventory_movement`
- `fct_reorder_events`
- `fct_procurement_order_lifecycle`
- `mart_branch_daily_operations`
- `mart_product_daily_demand`
- `mart_supplier_procurement_performance`

## Monetary-data boundary

Stage 5C does **not** invent price, cost, revenue, or margin. The current operational events
contain quantities and operational metadata only. Procurement explicitly keeps
`monetary_values_generated = false`, and a dbt data test fails if that invariant is broken.

## Master-data boundary

The current Silver warehouse does not contain the complete Product, Pharmacy Branch, and
Supplier master snapshots. Therefore Stage 5C does not fabricate `dim_product`,
`dim_branch`, or `dim_supplier` attributes from event IDs. A later warehouse extension will
publish the real master dimensions and enrich the Power BI star schema.

## Quality controls

- source event IDs are unique/non-null where applicable;
- unit-demand arithmetic is reconciled;
- fulfillment rates are bounded;
- inventory observed balances are non-negative;
- reorder quantities are non-negative;
- purchase-order lifecycle remains non-monetary;
- Gold model grains are explicitly tested for uniqueness;
- all Gold tables are verified after cloud build.
