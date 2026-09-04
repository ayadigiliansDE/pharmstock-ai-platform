# Stage 7G — Large-scale Spark / BigQuery Rebuild

## Purpose

Stage 7G rebuilds the million-scale Stage 7E operational history with Spark without replaying the
entire PostgreSQL database through Debezium/Kafka. It also closes the cutover gap with the Stage 7F
CDC stream.

```text
                         capture Kafka start offsets
                                  │
                                  ▼
Stage 7E PostgreSQL ── Spark JDBC historical snapshot ──► Parquet/Snappy
                                  │
                                  ▼
                         capture Kafka end offsets
                                  │
                                  ▼
Stage 7F Kafka CDC ── Spark exact [start,end) catch-up ──► CDC change log
                                  │
                                  ▼
                        reconcile changed tables
                                  │
                                  ▼
                      BigQuery-ready rebuild package
                                  │
                                  └─ end offsets become resume offsets
```

## Why the history does not go through Kafka

Stage 7F intentionally uses `snapshot.mode=no_data`. Stage 7E already holds millions of rows and a
13+ GB local PostgreSQL database. Re-emitting that complete state through Kafka would duplicate the
historical load and turn a CDC validation layer into a bulk-transfer mechanism.

Stage 7G therefore uses Spark JDBC for the historical baseline and Kafka only for changes that occur
across the snapshot cutover.

## Gap-free cutover

The checkpoint captures every Stage 7F topic's high watermark **before** the PostgreSQL snapshot.
After Spark finishes the snapshot it captures a second set of high watermarks. Spark then reads the
exact Kafka range `[start_offset,end_offset)`.

This means a row inserted, updated or deleted while the snapshot is running is not lost. If a CDC
managed table changed during that range, Stage 7G reconciles the latest event per primary key onto
the snapshot. Tables with no cutover changes are not duplicated on disk.

The ending offsets are persisted as `cdc_resume_offsets.json`; a later continuous consumer starts
from that boundary instead of replaying the cutover range.

## Snapshot scope

The rebuild contains 26 authoritative or production-like tables:

- Egyptian product and price master data
- 5,000-branch network master data
- commercial unit economics and branch policy
- POS terminals
- privacy-safe synthetic households/customers/loyalty/patient profiles
- prescription context and explicit demand/lost-demand history
- the 14 Stage 7F CDC-managed POS, inventory and procurement tables

Customer data remains `SYNTHETIC_CALIBRATED` and no direct customer PII is expected.

## Runtime

- Spark: `4.2.0`
- Spark Kafka connector: `org.apache.spark:spark-sql-kafka-0-10_2.13:4.2.0`
- PostgreSQL JDBC driver: `org.postgresql:postgresql:42.7.13`
- PostgreSQL source: Stage 7D/7E `pharmstock_ops`
- Output: Parquet with Snappy compression

## BigQuery boundary

The normal checkpoint performs **no cloud mutation**. It produces a BigQuery-ready rebuild plan
that maps every source table to `pharmstock_ops_rebuild.<schema>__<table>` and preserves the CDC
cutover log separately as `cdc_change_log`.

Cloud deployment remains an explicit action; Stage 7G acceptance never silently creates, replaces
or deletes a BigQuery resource.
