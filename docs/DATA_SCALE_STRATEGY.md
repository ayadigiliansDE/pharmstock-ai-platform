# PharmStock V2 — Real Data and Scale Strategy

## 1. Core rule

V2 will not contain a hard-coded list of 8 drugs or exactly 3 pharmacies.

The platform separates **master data** from **simulation configuration**:

```text
Drug master data (real registries) ----+
                                        +--> realistic pharmacy simulator
Synthetic pharmacy network ------------+
```

## 2. Drug catalog strategy

The target is a canonical catalog containing hundreds to tens of thousands of saleable pharmaceutical records.

Planned authoritative inputs:

1. Egyptian Drug Authority (EDA) information for Egypt-market alignment when a suitable lawful machine-readable or exported source is available.
2. RxNorm for normalized medication concepts and RxCUI identifiers.
3. openFDA NDC Directory for packaged marketed-product identifiers and manufacturer/labeler metadata.
4. DailyMed only when label/SPL data is needed; it is not required for every analytical use case.

The platform will not scrape captcha-protected interfaces or manufacture fake registry facts. Every imported product will retain source provenance and source identifiers.

## 3. Pharmacy-network strategy

Pharmacies in the simulator are synthetic business entities, but their distribution and behavior will be realistic.

The number of pharmacies will be a configuration value rather than code:

```text
PHARMACY_COUNT=1000
```

The simulator design will support scaling to thousands of branches without changing domain code.

Each simulated pharmacy will later have characteristics such as:

- governorate / city
- pharmacy type and size
- opening-hours profile
- local demand profile
- product assortment size
- initial inventory policy
- reorder policy
- sales volume profile
- seasonality and weekday behavior

Using synthetic pharmacy identities avoids pretending that generated transactional behavior belongs to real businesses, while still giving the platform realistic operational scale.

## 4. Product assortment

A pharmacy will not stock every drug equally. Later simulator stages will assign a product assortment based on pharmacy size and demand segment. Large branches may carry thousands of SKUs while smaller branches carry fewer.

## 5. Event volume

Event rate will also be configurable instead of tied to a fixed loop. This lets local development run cheaply while performance tests can increase throughput.

Planned configuration examples:

```text
PHARMACY_COUNT=1000
SIMULATION_SPEED=1.0
TARGET_EVENTS_PER_SECOND=250
```

Exact defaults will be chosen in Stage 2 after benchmarking the developer machine and local Kafka/Spark setup.

## 6. Data-quality rule

Incoming external catalog records will later pass through four states:

```text
raw -> parsed -> validated -> canonical
                  |
                  +--> quarantine (invalid/unmappable records)
```

Bad source rows are therefore observable rather than silently dropped.

## Stage 1B update

The pharmacy master now separates business organizations from individual branches. This supports independent pharmacies, chains, hospital networks and digital operators without hard-coding branch count. Branch records carry location, weekly operating profile and physical/assortment capacity; transactional inventory and sales remain separate.
