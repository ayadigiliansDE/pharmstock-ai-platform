# Stage 2D — Scale Hardening + FEFO

Stage 2D adds two production-oriented capabilities without introducing Kafka yet.

## 1. Bounded-memory inventory generation

Stage 2C is intentionally easy to understand: it generates all branch inventory rows in memory
and writes them at the end. That is useful for a small checkpoint, but not appropriate for a large
network where millions of branch/product and batch rows may be created.

Stage 2D adds a streaming export path:

```text
Generate one branch
      ↓
Write branch inventory rows
      ↓
Write branch batch rows
      ↓
Write branch summary
      ↓
Release that branch's generated rows
      ↓
Generate next branch
```

Output is partitioned:

```text
artifacts/stage2d/
├── inventory/
│   ├── part-00001.csv
│   ├── part-00002.csv
│   └── ...
├── batches/
│   ├── part-00001.csv
│   ├── part-00002.csv
│   └── ...
├── branch_assortment_summary.csv
└── inventory_manifest.json
```

The manifest explicitly records `export_mode = bounded_memory_partitioned_csv` and the partition
size used by the run.

## 2. FEFO batch consumption

FEFO means **First Expired, First Out**. For one branch/product, the usable batch with the earliest
expiry date is consumed first. Expired batches are never allocated.

The FEFO rule lives in the domain layer (`pharmstock.domain.batches`), not in Kafka, Spark, or a
future database. Infrastructure transports or stores decisions; it does not decide which batch
should be sold.

Stage 2D does not yet build the complete sales-demand engine. It provides the validated batch
allocation primitive that the future sales engine will call.

## Data-truth boundary

The catalog used in the current simulator is an official U.S. openFDA NDC catalog while the
pharmacy network is a synthetic Egyptian network. All current branch/product mappings remain
explicitly labeled `synthetic_cross_market_mapping`. Stage 2D still does not invent Egyptian market
prices.
