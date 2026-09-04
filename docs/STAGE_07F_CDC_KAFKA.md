# Stage 7F — Debezium CDC → Kafka

## Purpose

Stage 7F turns the Stage 7D/7E PostgreSQL source of record into a live CDC source. PostgreSQL
logical WAL is decoded by Debezium and emitted as table-specific Kafka change events.

```text
PostgreSQL 18.6
  logical WAL / pgoutput
        ↓
Debezium PostgreSQL Connector 3.6
        ↓
Kafka 4.3.1
        ↓
pharmstock.ops.<schema>.<table>
```

## Source boundary

Stage 7D already created:

- replication user `pharmstock_cdc`
- publication `pharmstock_cdc_publication`
- `wal_level=logical`
- the 13 published operational tables

Stage 7F creates/uses the canonical replication slot `pharmstock_cdc_slot` and deploys the
Debezium connector `pharmstock-postgres-cdc`.

## Snapshot policy

The Stage 7F checkpoint uses `snapshot.mode=no_data` intentionally. Stage 7E already populated a
large historical operational database. Re-emitting the entire database through Kafka merely to
validate CDC would produce millions of snapshot records and unnecessarily duplicate the historical
load.

Therefore:

- Stage 7F owns **new operational changes** from PostgreSQL WAL onward.
- Stage 7G owns the **controlled historical rebuild** into Spark/BigQuery and the merge with the CDC
  stream.

This boundary keeps the local learning checkpoint visible and bounded while preserving a
production-style source-of-record architecture.

## Kafka topics

One topic is created for every published operational table using this naming rule:

```text
pharmstock.ops.<schema>.<table>
```

Examples:

- `pharmstock.ops.pos.sale_header`
- `pharmstock.ops.inventory.stock_movement`
- `pharmstock.ops.procurement.supplier`

Each Stage 7F CDC topic uses three partitions, replication factor 1 for local development, and a
seven-day delete retention policy.

## Acceptance probe

The checkpoint creates an isolated synthetic supplier row, updates it, and deletes it. The row is
used only to prove the CDC path and is removed before success is recorded.

The expected Debezium operation sequence is:

```text
c -> u -> d
```

where `c` is create, `u` is update, and `d` is delete.

## Truth and privacy boundary

Stage 7F does not fabricate new customer data and does not mutate any cloud resource. The probe row
is explicitly `SYNTHETIC_CALIBRATED` and contains no customer PII.
