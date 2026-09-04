# Stage 2B — Real Drug Catalog Ingestion

## Goal
Replace the fixed demo list of eight medicines with a repeatable ingestion pipeline that reads real official drug-registry records and builds PharmStock's canonical `Product` master.

## First official source
Stage 2B uses the **openFDA National Drug Code (NDC) Directory**.

Important boundary: this is authoritative source data for the **United States market**. `market_code` is therefore `US`. It is not treated as Egyptian registration data. A later market adapter can ingest an official EDA export/API without changing the canonical domain model.

## Flow

```text
openFDA NDC API
      ↓
RAW JSON records
      ↓
Source validation
      ↓
Normalization
      ↓
Package-level Product SKUs
      ↓
Canonical CSV + JSON
      ↓
Rejected-row quarantine + summary
```

## Why package-level expansion?
One NDC product can have multiple marketed package sizes. PharmStock expands those packages into separate saleable canonical SKUs while preserving the common NDC product code.

## Data lineage
Every accepted product keeps:
- source system (`openfda_ndc`)
- source record identity
- source update timestamp when supplied by the API
- NDC product code
- NDC package code when present
- RxCUI when openFDA harmonization provides it

## Deterministic IDs
Canonical `product_id` values are generated with UUID5 from source identity. Re-running the same source package produces the same PharmStock ID.

## Raw and quarantine layers
No source row silently disappears:
- `openfda_ndc_raw.jsonl` retains the source payload received in this run.
- `rejected_records.jsonl` records invalid rows and their validation reason.
- `ingestion_summary.json` exposes counts used for acceptance checks.

## Current scope
Stage 2B is ingestion and normalization only. It does not yet:
- claim Egyptian market availability;
- create pharmacy-specific prices;
- allocate products to pharmacy inventory;
- enrich every product through RxNorm API calls;
- download the complete NDC bulk snapshot.

Those are deliberately separate stages.
