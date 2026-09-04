# Stage 7D — On-Prem PostgreSQL Operational / POS Database

Stage 7D changes the production digital twin from artifact-only simulation into an operational
source-of-record boundary that resembles a deployable pharmacy platform. The database is local
Docker infrastructure and performs **no cloud mutation**.

## Runtime

- PostgreSQL image: `postgres:18.6`
- Database: `pharmstock_ops`
- Windows host endpoint: `localhost:5433`
- Admin role: `pharmstock_admin`
- Application role: `pharmstock_app`
- Future CDC role: `pharmstock_cdc`
- Password encryption: SCRAM-SHA-256
- `wal_level=logical`
- `max_replication_slots=10`
- `max_wal_senders=10`

PostgreSQL 18.6 is pinned rather than using `latest`. Stage 7D does not deploy Debezium yet, but
its CDC contract targets Debezium 3.6.1.Final, PostgreSQL `pgoutput`, publication
`pharmstock_cdc_publication`, and future slot `pharmstock_cdc_slot`.

## Schemas

```text
master       Egypt product/price snapshots + production-like pharmacy network
commercial   calibrated product economics + branch commercial policy
pos          terminals, sale headers/lines, payments, returns
inventory    batches, positions, immutable stock movements
procurement  suppliers, purchase orders, goods receipts
audit        ingestion runs
staging      transient CSV loading boundary
```

The operational transaction tables are schemas only at this stage. Stage 7D does not fabricate a
historical POS transaction corpus. Stage 7E will create the high-volume transaction simulator and
write through the operational database.

## Truth boundary

- Product and retail price: `PUBLIC_MARKET_EGYPT` from Stage 7A.
- Pharmacy identities and operational traits: `SYNTHETIC_CALIBRATED` from Stage 7B.
- Purchase cost / commercial policy: `SYNTHETIC_CALIBRATED` from Stage 7C.
- Stage 7D generated POS transactions: none.

## Loading behavior

The loader truncates only `staging.*`. Production master/commercial tables are loaded with
`INSERT ... ON CONFLICT DO UPDATE`; it never truncates the target masters. This allows the
operational database to remain usable after later transaction stages are added.

POS terminals are generated deterministically from each branch's `checkout_points`, so the
terminal count is expected to equal the sum of checkout points in the 5,000-branch snapshot.

## CDC readiness

Stage 7D pre-creates a publication for 13 operational tables and a dedicated replication role.
It does **not** create a replication slot or run a connector yet. Slot lifecycle starts with the
Debezium stage so abandoned local slots cannot retain WAL unexpectedly.
