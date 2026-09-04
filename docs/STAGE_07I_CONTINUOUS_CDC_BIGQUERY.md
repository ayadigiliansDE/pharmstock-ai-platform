# Stage 7I — Continuous CDC to BigQuery with a Sandbox-safe Delta Overlay

## Objective

Continue from the verified Stage 7H historical baseline without replaying historical
rows through Kafka and without producing full-table copies in BigQuery.

The runtime path is:

`PostgreSQL -> Debezium -> Kafka -> Spark deterministic micro-batch -> BigQuery CDC delta`

The Stage 7H raw tables remain the immutable historical baseline. A separate current-state
dataset exposes views that overlay the latest CDC event per primary key on that baseline.

## Why append-only delta instead of MERGE

The active environment is BigQuery Sandbox. The production design would normally use
streaming and/or MERGE-based upserts. The sandbox execution path deliberately avoids those
operations and uses BigQuery load jobs plus views. This preserves the production CDC
boundary while respecting the sandbox runtime.

## Storage safety

The project currently operates close to the Sandbox storage ceiling. Stage 7I therefore:

- never rewrites the 31,954,735-row Stage 7H baseline;
- never creates a full raw staging copy;
- appends only new CDC events;
- creates zero-storage current-state views;
- processes at most 50,000 CDC records per micro-batch by default;
- checks visible project storage before every batch;
- estimates the post-load peak conservatively from local Parquet size;
- warns at 8.2 GiB;
- stops before upload at 8.5 GiB;
- advances offsets only after BigQuery verification.

If the guard stops a batch, no Kafka offset state is lost. The local batch remains under
`artifacts/stage7i/batches/<batch_id>` and can be retried later.

## Exactly-once recovery boundary

Each batch is derived from explicit Kafka `[start,end)` offsets. The batch id is a stable
hash of those offsets. Every local Parquet part is loaded with a deterministic BigQuery job
id. A retry reuses an already-successful job instead of intentionally appending it again.
The current-state views also deduplicate by `event_id` as a second semantic safeguard.

## Current-state layer

Dataset: `pharmstock_ops_current`

The layer contains 26 views with the same `<schema>__<table>` naming convention as the
Stage 7H raw dataset:

- 14 CDC-managed views = baseline + latest CDC overlay;
- 12 non-CDC views = direct passthrough to the Stage 7H baseline.

Deletes suppress the baseline row, updates replace it, and inserts add a new current row.
No raw historical table is copied to implement this behavior.

## Sandbox longevity limitation

Sandbox-managed tables retain the platform's Sandbox expiration policy. Stage 7I is a
production-style local/cloud integration demonstration, but long-running production CDC
retention ultimately requires a billing-enabled BigQuery project or another durable cloud
serving target. The worker intentionally does not hide that constraint.
