# Stage 7H — BigQuery Rebuild Deployment + dbt Analytics

## Purpose

Stage 7H is the explicit cloud deployment boundary after the accepted Stage 7G rebuild. It loads
the 26 gap-safe Parquet snapshot tables into `pharmstock_ops_rebuild`, validates row counts and
primary-key uniqueness, promotes only after all staging checks pass, and then runs Stage 7H dbt
models on the deployed raw rebuild.

```text
Stage 7G BigQuery-ready Parquet
             │
             ▼
   stage all 26 BigQuery tables
             │
             ▼
 row-count + primary-key validation
             │
             ▼
 per-table atomic CREATE OR REPLACE
             │
             ▼
       pharmstock_ops_rebuild
             │
             ▼
 dbt rebuild_staging/intermediate/gold
             │
             ▼
  pharmstock_rebuild_gold marts
```

## Safety boundary

`python scripts/run_checkpoint.py 7h` is local-only and performs **no cloud mutation**. It verifies
Stage 7G PASS, all Parquet paths, the 31M+ expected row manifest, dbt project files, dependency
availability and Google credential hints.

Cloud mutation requires an explicit second command with both `--execute` and `--replace`.
No checkpoint silently creates or replaces BigQuery resources.

## BigQuery deployment

- Raw dataset default: `pharmstock_ops_rebuild`
- 26 Stage 7G tables are loaded from Parquet.
- All 26 staging tables must pass expected row-count validation before promotion begins.
- Every table is checked for duplicate primary keys.
- Final replacement uses `CREATE OR REPLACE TABLE` per table.
- Large timestamped facts use date partitioning and branch/product/supplier clustering where useful.
- The Stage 7G CDC resume offsets are preserved; historical rows are not replayed through Kafka.

## dbt rebuild analytics

Stage 7H adds a new dbt namespace rather than rewriting the earlier Stage 5 models:

- `rebuild_staging`: normalized views over the Stage 7H raw BigQuery rebuild
- `rebuild_intermediate`: daily sales, demand, inventory and procurement grains
- `rebuild_marts`: branch, product and supplier performance marts

The marts can use EGP sales/cost/profit fields because Stage 7C/7E explicitly produced financial
state. Retail price provenance remains `PUBLIC_MARKET_EGYPT`; generated operational/customer and
cost behavior remains explicitly calibrated/synthetic where defined by the source contracts.

## Authentication

BigQuery execution uses Google Application Default Credentials (ADC) and the explicit
`PHARMSTOCK_BQ_PROJECT` project. The cloud command verifies the configured dataset location before
loading data.
