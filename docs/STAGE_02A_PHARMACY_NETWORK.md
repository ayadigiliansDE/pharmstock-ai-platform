# Stage 2A — Large Synthetic Pharmacy Network

## Goal

Replace the original three-pharmacy demo assumption with a configurable network that can
represent tens, hundreds, thousands or more fictional pharmacy branches without changing
business-domain code.

## What is real vs synthetic

**Real public anchor:**

- Egypt's 27 governorates.
- CAPMAS population estimates by governorate for 1 January 2024.
- Population is used only as a branch-allocation weight.

**Synthetic simulation data:**

- pharmacy organization names
- branch names and identifiers
- ownership pattern
- branch scale
- capacity
- service modes
- opening profile

This separation is intentional. We do not invent sales or business attributes and then
present them as observations about real Egyptian pharmacy companies.

## New modules

```text
src/pharmstock/simulation/
├── geography.py
├── network.py
└── __init__.py
```

### `geography.py`

Contains the 27-governorate reference and the 1/1/2024 population weights. A validation
function checks both the number of governorates and the CAPMAS table total so accidental
edits fail fast.

### `network.py`

Builds deterministic synthetic organizations and branches. The same seed produces the
same generated branch identities and distribution.

The generator reuses Stage 1B domain validation; it does not bypass it. Every generated
branch is a real `PharmacyBranch` object before it is exported.

## Allocation method

For `N` branches:

1. Compute each governorate's population share.
2. Multiply that share by `N`.
3. Take integer floors.
4. Allocate remaining branches using the largest-remainder method.

For a 1,000-branch run, every one of the 27 governorates receives at least one branch.

## Why generated companies are fictional

A realistic simulator needs variation, but inventing transactions for named real
companies would make synthetic data easy to mistake for factual company data. V2 uses
clearly synthetic company names while retaining real geography as the public anchor.

## Current limitations — intentionally deferred

Stage 2A distributes at governorate level and uses a representative city for each
profile. It is **not yet** a city/district-level facility-location model.

Later Stage 2 work will add:

- richer city/markaz/district geography from authoritative sources
- real drug catalog ingestion
- branch assortment generation
- batch inventory
- demand and sales generation
- replenishment behavior

## Run it

Small preview:

```powershell
python scripts\run_stage2a_network.py --pharmacies 25 --output artifacts\stage2a-25
```

Large checkpoint:

```powershell
python scripts\run_stage2a_network.py --pharmacies 1000 --output artifacts\stage2a-1000
```

Then open `pharmacy_branches.csv` in Excel and `network_summary.json` in VS Code.

See `docs/LOCAL_RUN_GUIDE.md` for first-time environment setup and checkpoint replay.
