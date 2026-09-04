# PharmStock V2 — Stage 7D patch (v0.25.0)

Adds the local on-prem PostgreSQL operational/POS source-of-record boundary.

Key additions:

- PostgreSQL 18.6 Docker service on local port 5433.
- Logical-WAL/SCRAM configuration for future CDC.
- Master, commercial, POS, inventory, procurement, audit and staging schemas.
- Idempotent Stage 7A/7B/7C master seed loader using staging + upsert.
- Deterministic POS terminal generation from branch checkout capacity.
- Application and CDC roles with least-purpose schema grants.
- Pre-created `pgoutput` publication for 13 operational tables.
- No replication slot / Debezium connector yet.
- Local verification and CDC-readiness artifacts.
- Visible checkpoint: `python scripts/run_checkpoint.py 7d`.
