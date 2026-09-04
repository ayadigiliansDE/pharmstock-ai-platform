# Stage 6A — Power BI Serving / Semantic Contract

## Goal

Create a stable BigQuery serving boundary for Power BI instead of coupling reports directly
to the internal Gold warehouse tables.

## BigQuery dataset

`pharmstock_pbi`

The dataset contains eleven dbt views:

- dim_date
- dim_product
- dim_branch
- dim_supplier
- fact_sales_demand
- fact_inventory_movement
- fact_reorder_events
- fact_procurement_order_lifecycle
- mart_branch_daily_operations
- mart_product_daily_demand
- mart_supplier_procurement_performance

## Semantic contract

The local checkpoint writes:

- `artifacts/stage6a/semantic_model_contract.json`
- `artifacts/stage6a/bigquery_connection.m`
- `artifacts/stage6a/measures.dax`
- `artifacts/stage6a/local_verification.json`

The contract defines a star-schema/constellation model with one-to-many, single-direction
relationships and explicit DAX measures. No authoritative monetary measures are generated.

## Safety

`run_checkpoint.py 6a` and `run_stage6a_powerbi.py` without `--execute` never mutate cloud
resources. `--execute` creates/replaces only the dedicated dbt serving views.
