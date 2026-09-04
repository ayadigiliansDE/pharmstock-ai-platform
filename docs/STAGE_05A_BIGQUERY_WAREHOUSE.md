# Stage 5A — BigQuery Warehouse Foundation

Stage 5A establishes a cloud-safe warehouse boundary after Stage 4B Silver.

## Why there is a local mode first

A graduation/development checkpoint must be inspectable without requiring a Google Cloud
account, credentials, billing, or network mutation. Therefore the default Stage 5A checkpoint:

1. reads the completed Stage 4B Silver Parquet tables with Spark 4.2.0;
2. validates their columns and Spark data types against explicit BigQuery contracts;
3. rewrites the data as Snappy Parquet with `event_date` materialized inside each file;
4. generates BigQuery schema JSON files, DDL, and a dry-run load plan;
5. performs no Google Cloud API call.

## Warehouse tables

Seven tables are defined in dataset `pharmstock_silver` by default:

- `event_index`
- `sales_units_fulfilled`
- `inventory_quantity_changed`
- `inventory_reorder_required`
- `purchase_order_created`
- `goods_receipt_received`
- `restock_applied`

All tables are partitioned by `event_date`. Clustering fields are table-specific and are chosen
from branch, product, supplier, event-type, and aggregate identifiers.

## Why Stage 5A rewrites the Parquet

Stage 4B writes Spark Silver tables partitioned in Hive-style directories such as
`event_date=2026-08-22/`. In that representation the partition value may live in the directory
path rather than inside each individual Parquet file. The optional local-file BigQuery loader
must be able to see `event_date` as a real column, so Stage 5A writes warehouse-ready Parquet
without Hive directory partitioning.

## Data truth and lineage

Stage 5A does not invent or enrich business values. It preserves the Stage 4B normalized facts,
including Kafka topic/partition/offset and the semantic event hash. Sales remain unit-based and
non-monetary because authoritative pricing has not been introduced.

## Cloud execution safety

`run_checkpoint.py 5a` never mutates BigQuery. The optional loader is a separate command and is
dry-run by default. Actual cloud mutation requires an explicit project plus both `--execute` and
`--replace`.

The BigQuery Python client is an optional dependency (`google-cloud-bigquery==3.43.0`) and is
not installed into the core application environment unless the `gcp` extra is selected.
