# Stage 5B — Real BigQuery Cloud Integration

Stage 5B turns the Stage 5A warehouse handoff into an explicit, cloud-safe BigQuery deployment path.
The normal checkpoint remains local and performs no cloud mutation.

## Contracts

- Source: `artifacts/stage5a/warehouse_ready`.
- Destination: one BigQuery dataset containing the seven Stage 5A tables.
- Authentication: Application Default Credentials (ADC) or an explicit credential path supported by Google Auth.
- Default dataset: `pharmstock_silver`.
- Default location: `EU`.
- No service-account key is stored in the repository.

## Safe load strategy

For each table:

1. Create a run-scoped staging table with the exact schema, partition field and clustering contract.
2. Upload all local Parquet parts into staging.
3. Verify staging row count equals Stage 5A expected rows.
4. Ensure the target table metadata matches the contract.
5. Verify every logical `REQUIRED` field is non-null in staging.
6. Atomically rebuild target with explicit `NOT NULL` schema using `CREATE OR REPLACE TABLE ... AS SELECT`.
6. Verify final target row count and metadata.
7. Delete the staging table.

This avoids exposing a partially loaded target when one local-file upload fails before promotion.

## Safety

`python scripts/run_checkpoint.py 5b` never connects to Google Cloud and never mutates cloud resources.
The live loader is dry-run by default. Mutation requires `--execute --replace` and a real project ID.
