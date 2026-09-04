# Stage 1B — Pharmacy Domain Model

## Goal

Model pharmacies as scalable master data rather than a hard-coded list of three demo stores.

The central distinction is:

```text
PharmacyOrganization
        |
        +---- PharmacyBranch 001
        +---- PharmacyBranch 002
        +---- PharmacyBranch ...
```

An independent pharmacy can be represented as one organization with one branch. A chain or hospital network can own hundreds of branches without changing the domain model.

## 1. PharmacyOrganization

`PharmacyOrganization` represents the business/operator identity. It contains stable facts such as:

- UUID organization identifier
- human/business code
- legal name
- display name
- organization type
- market code

Supported organization types at this checkpoint are independent, chain, hospital network and digital operator.

## 2. PharmacyBranch

`PharmacyBranch` represents one physical or fulfillment facility. It references its parent organization and contains:

- immutable branch UUID
- organization UUID
- branch code
- display name
- pharmacy/facility type
- scale segment
- location
- weekly operating profile
- capacity profile
- operational status
- optional opening date

The domain contract does **not** enforce global branch-code uniqueness. Cross-record uniqueness is a persistence/repository concern and will be enforced when a real storage layer is introduced.

## 3. BranchLocation

A branch location contains administrative geography and optional coordinates:

```text
country -> governorate -> city -> district -> address
```

Latitude and longitude are optional, but they must be supplied as a pair. This allows early imported/synthetic data to exist before geocoding while preventing half-valid coordinate records.

## 4. OperatingProfile

Every operating profile requires exactly seven unique weekday rules. A day can be:

- normally open with opening and closing time
- explicitly closed
- explicitly 24 hours

Overnight ranges are valid, for example `18:00 -> 02:00`.

The profile also stores an IANA timezone and supported service modes such as in-store, delivery, click-and-collect and online fulfillment.

## 5. CapacityProfile

Capacity is stable branch metadata that constrains the later simulator. It includes:

- maximum active assortment size in SKUs
- total storage capacity in units
- optional floor area
- checkout-point count
- cold-chain capability and capacity

The model validates impossible combinations such as cold-chain units on a branch that does not support cold chain.

`PharmacyScale` intentionally does not hard-code fixed capacity ranges. Stage 2 will use realistic generation policies to produce correlated values while still allowing real-world exceptions.

## 6. What is deliberately NOT in this model

These values change over time and therefore belong to Stage 1C or later services:

- stock on hand
- reserved stock
- pharmacy-specific price
- sale transactions
- purchase/restock transactions
- reorder points
- demand level
- forecast values
- daily transaction counts

This separation prevents master data from becoming mixed with mutable operational state.

## 7. Why this scales beyond three pharmacies

No branch list is embedded in code. Stage 2 will generate organizations and branches from configuration and distributions, for example:

```text
PHARMACY_COUNT=1000
SIMULATION_MARKET_CODE=EG
SIMULATION_TIMEZONE=Africa/Cairo
```

The same domain objects can therefore represent 10, 1,000 or 10,000 branches. Scale is controlled by the simulator/data layer, not by changing the domain classes.

## 8. Files introduced

- `src/pharmstock/domain/pharmacy.py`
- `tests/test_pharmacy_domain.py`

The public domain package export was updated in `src/pharmstock/domain/__init__.py`.
