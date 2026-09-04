# Stage 7A — Egyptian Pharmaceutical Master

Stage 7A replaces the U.S.-oriented demo product master as the future production baseline with an
Egypt-oriented, provenance-aware pharmaceutical market snapshot.

## Truth model

The stage deliberately separates regulatory truth from public market observations:

- `OFFICIAL_EGYPT`: reserved for data verified directly against the Egyptian Drug Authority (EDA).
- `PUBLIC_MARKET_EGYPT`: real/public Egyptian-market observations that are not claimed to be an
  official EDA export.
- `SYNTHETIC_CALIBRATED`: simulation-only values generated later for fields that have no public,
  authoritative source.

The default Stage 7A dataset is the CC0 Egyptian Drug Database public snapshot (June 2026). It
contains Arabic/English trade names, scientific composition, manufacturer, drug class, route, and
EGP retail price. It is used as `PUBLIC_MARKET_EGYPT`, not as an EDA registration assertion.

## EDA boundary

EDA's EDDB is the regulatory reference for valid registered products. Its documented public search
flow includes a verification-code step. PharmStock must not automate around that control.

The EDA Pharma Data Hub documentation also establishes production fields such as GTIN, package
specification, priced packages, and manufacturer roles. Stage 7A therefore creates an
`eda_verification_queue.csv` and an `eda_reference_contract.json`. Registration number, GTIN,
license status, price status, and official price verification stay blank/pending until an authorized
EDA export/API response is available.

## Outputs

`artifacts/stage7a/` contains:

- `egypt_product_master.csv`
- `product_price_history.csv`
- `eda_verification_queue.csv`
- `rejected_market_records.csv`
- `data_quality_report.json`
- `source_snapshot_manifest.json`
- `eda_reference_contract.json`
- `_SUCCESS`

The source file is cached under `artifacts/source_cache/` and its SHA-256 is written into the
manifest for reproducibility.

## Acceptance

- at least 20,000 accepted medicine products by default;
- all accepted products have scientific composition and a positive EGP retail price;
- deterministic product IDs and no duplicate market product keys;
- no synthetic products in the master;
- no fabricated EDA registration numbers or GTINs;
- all market prices explicitly marked as non-official until EDA verification;
- no cloud mutation in Stage 7A.
