# PharmStock AI Platform V2

> **Windows note:** IANA time zones such as `Africa/Cairo` require the project
> dependency `tzdata==2026.3`. If upgrading an existing `.venv`, rerun
> `python -m pip install -e ".[dev]"` before `pytest`.


Production-style rebuild of the original graduation project.

> The original project is a **read-only reference**. V2 is built independently, layer by layer, so every architectural decision and every line of code can be understood and tested as it is introduced.

## Current checkpoint

**Stage 7F — Debezium CDC → Kafka**

Completed so far:

- Stage 0 engineering foundation
- Python package layout (`src/pharmstock`)
- Python 3.14.x project target
- canonical pharmaceutical Product contract
- cross-registry identifiers and provenance
- Product validation tests
- scalable pharmacy organization/branch domain
- branch location, operating schedule and capacity validation
- inventory state, reorder policy and immutable stock movements
- completed sale and batch-aware restock receipt contracts
- versioned, correlation-aware domain-event envelopes
- real-data and simulator scale strategy
- CAPMAS-weighted 27-governorate pharmacy network generator
- deterministic synthetic organization/branch generation
- CSV/JSON artifact export for local inspection
- permanent local checkpoint runner and Windows run guide
- bounded-memory partitioned inventory export + FEFO
- structured multi-day demand simulation with stockouts and reorder triggers
- ending inventory/batch state for continuation into later stages
- synthetic supplier master + purchase orders + lead times + goods receipts
- capacity-aware replenishment with new stock batches and restock movements
- scalable 153-supplier synthetic ecosystem with branch supplier panels and supplier utilization
- local Apache Kafka 4.3.1 foundation and managed business topics
- deterministic Stage 2E/2F.1 operational event replay into Kafka
- durable SQLite inbox ledger keyed by event_id
- duplicate suppression, payload-conflict detection and dead-letter routing
- source-offset commits only after a durable processed/duplicate/failed outcome
- Spark Structured Streaming Kafka → Bronze with restart-safe checkpoints
- Silver event parsing, deduplication, conflict audit and typed normalization
- seven BigQuery warehouse contracts + BigQuery-ready local Parquet export
- deterministic BigQuery DDL/schema/load-plan generation with no cloud mutation by default

The local Kafka → Bronze → Silver → warehouse-contract path is now implemented. Actual BigQuery
cloud loading, dbt, ML, RAG, Airflow, and Power BI are introduced in later stages one step at a time.

## Python baseline

V2 targets the latest stable Python feature line used for this checkpoint:

```text
Python >=3.14,<3.15
```

Python 3.15 is not used while it is still a pre-release line.

## Data-scale principle

The original demo limits are removed from the V2 design:

- drug products are not hard-coded to 8 records
- pharmacy count is not hard-coded to 3 branches
- the product master is designed for authoritative external registries
- the simulator will generate a configurable large synthetic pharmacy network
- source provenance is retained for every imported product

See [`docs/DATA_SCALE_STRATEGY.md`](docs/DATA_SCALE_STRATEGY.md).

## Target architecture

```text
Real Drug Registries -> Canonical Product Master ----+
                                                     |
Synthetic Pharmacy Network --------------------------+--> Validated Events
                                                            |
                                                            v
                                                          Kafka
                                                            |
                                                            v
                                                  Spark Structured Streaming
                                                            |
                                                            v
                                                     BigQuery Raw
                                                            |
                                                            v
                                         dbt Staging -> Intermediate -> Marts
                                                            |
                                         +------------------+------------------+
                                         |                                     |
                                      Power BI                           ML Feature Mart
                                                                               |
                                                                       MLflow / Forecasts
                                                                               |
                                                                           Power BI
```

AI/RAG remains an independent service/API rather than being embedded in the BI data-processing path.

## Project structure

```text
pharmstock-ai-platform-v2/
├── src/pharmstock/
│   ├── domain/          # Product, Pharmacy, Inventory, Sale... domain contracts
│   ├── ingestion/       # Future source adapters and Kafka producers
│   ├── streaming/       # Kafka transport, replay, durable inbox + DLQ processing
│   ├── analytics/       # Bronze/Silver analytics contracts
│   ├── warehouse/       # BigQuery schemas, DDL and cloud-safe load planning
│   ├── ml/              # Future training/evaluation/prediction code
│   ├── ai/              # Future RAG / AI service code
│   └── common/          # Shared config, logging and utilities
├── dbt/
├── airflow/dags/
├── powerbi/
├── infra/
├── spark/jobs/          # Container-run PySpark jobs
├── tests/
├── docs/
├── scripts/
├── .env.example
├── .gitignore
└── pyproject.toml
```

## Stage roadmap

| Stage | Deliverable |
|---|---|
| 0 | Foundation + target architecture ✅ |
| 1A | Product domain model + scale/data strategy ✅ |
| 1B | Pharmacy domain model ✅ |
| 1C | Inventory, Sale, Restock + versioned event contracts ✅ |
| 2A | Large CAPMAS-weighted synthetic pharmacy network ✅ |
| 2B | Real drug catalog ingestion + canonicalization ✅ |
| 2C | Branch assortment + initial stock + batch/expiry simulation ✅ |
| 2D | Bounded-memory partitioned inventory export + FEFO ✅ |
| 2E | Structured demand, unit fulfillment, stockouts + ending inventory ✅ |
| 2F | Capacity-aware procurement, purchase orders, deliveries + restock batches ✅ |
| 2F.1 | 153-supplier scalable ecosystem, branch panels + utilization ✅ |
| 3A | Kafka broker/topics + single-event round trip ✅ |
| 3B | Operational simulator event streaming ✅ |
| 3C | Durable consumer inbox, idempotency + DLQ processing ✅ |
| 4A | Spark Structured Streaming Kafka → Bronze + checkpoint restart ✅ |
| 4B | Silver parsing, deduplication + event-specific normalization ✅ |
| 5A | BigQuery warehouse contracts + local cloud-safe export ✅ |
| 5B | BigQuery cloud load ✅ |
| 5C | dbt staging/intermediate/gold analytics ✅ |
| 5D | Master-data warehouse dimensions ✅ |
| 6A | Power BI serving / semantic contract ✅ |
| 6B | Power BI Desktop build kit + connection validation ✅ |
| 7A | Egyptian-market pharmaceutical master + EGP price history ✅ |
| 7B | 5,000-branch calibrated Egyptian pharmacy network ✅ |
| 7C | Pricing / financial engine ✅ |
| 7D | On-prem PostgreSQL operational / POS source of record ✅ |
| 7E | Million-scale historical POS / operational simulation ✅ |
| 7F | Debezium CDC → Kafka ✅ |
| 7G | Large-scale Spark / BigQuery rebuild ✅ |
| 7H | BigQuery rebuild deployment + dbt analytics |
| 8 | ML feature platform + MLflow + predictive models |
| 9 | AI Assistant / RAG / governed analytics tools |
| 10 | Final production Power BI dashboard |
| 11 | Orchestration, observability, security, CI/CD |

## Local setup

Requires Python 3.14.x.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
pytest
ruff check .
```

## Run the project locally and watch it evolve

Start with [`docs/LOCAL_RUN_GUIDE.md`](docs/LOCAL_RUN_GUIDE.md). Every checkpoint remains runnable:

```powershell
python scripts\run_checkpoint.py 1c
python scripts\run_checkpoint.py 2a
python scripts\run_checkpoint.py 2b
python scripts\run_checkpoint.py 2c
python scripts\run_checkpoint.py 2d
python scripts\run_checkpoint.py 2e
python scripts\run_checkpoint.py 2f
python scripts\run_checkpoint.py 2f1
python scripts\run_checkpoint.py 3a
python scripts\run_checkpoint.py 3b
python scripts\run_checkpoint.py 3c
python scripts\run_checkpoint.py 4a
python scripts\run_checkpoint.py 4b
python scripts\run_checkpoint.py 5a
python scripts\run_checkpoint.py 5b
python scripts\run_checkpoint.py 5c
python scripts\run_checkpoint.py 5d
python scripts\run_checkpoint.py 6a
python scripts\run_checkpoint.py 6b
python scripts\run_checkpoint.py 7a
python scripts\run_checkpoint.py 7b
python scripts\run_checkpoint.py 7c
python scripts\run_checkpoint.py 7d
python scripts\run_checkpoint.py 7e
python scripts\run_checkpoint.py 7f
python scripts\run_checkpoint.py 7g
python scripts\run_checkpoint.py 7h
```

For the current stage, study these files first:

1. `docs/STAGE_07E_HISTORICAL_POS_SIMULATOR.md`
2. `docs/STAGE_07E_LOCAL_RUN.md`
3. `src/pharmstock/simulation/pos_history.py`
4. `infra/docker/postgres/sql/005_stage7e_support.sql`
5. `infra/docker/postgres/sql/006_generate_stage7e_history.sql`
6. `infra/docker/postgres/sql/007_verify_stage7e_history.sql`
7. `scripts/run_stage7e_history.py`
8. `tests/test_stage7e_history.py`

## Current checkpoint: Stage 7E
Stage 7E turns the accepted Stage 7D PostgreSQL source of record into a deterministic,
production-like historical pharmacy workload. The default acceptance profile covers 5,000
branches for 14 days and must produce at least 1.2 million sale headers and 2.0 million sale
lines, plus payments, explicit demand/lost-demand, inventory movements, returns and procurement.
The 365-day `prod_like` path is guarded because it can create tens of millions of transactions.
See `docs/STAGE_07E_LOCAL_RUN.md`.



## Current checkpoint: Stage 7F

Stage 7F activates the PostgreSQL logical-WAL boundary prepared in Stage 7D and streams new
operational mutations through Debezium 3.6 into table-specific Kafka topics. The checkpoint uses
`snapshot.mode=no_data` deliberately: the million-scale Stage 7E history stays in PostgreSQL and is
rebuilt in Stage 7G, while Stage 7F proves the live CDC path with an isolated supplier
INSERT → UPDATE → DELETE probe. No cloud mutation occurs.

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 7f
```

See `docs/STAGE_07F_CDC_KAFKA.md` and `docs/STAGE_07F_LOCAL_RUN.md`.

## Stage 5C — dbt Analytics / Gold Layer

Stage 5C builds governed BigQuery analytics models with dbt. The live Silver dataset remains
`pharmstock_silver`; dbt creates staging views in `pharmstock_stg` and Power BI-ready tables
in `pharmstock_gold`. The layer intentionally contains no fabricated prices, revenue, costs,
or margins. Full master dimensions are deferred until their authoritative snapshots are loaded.

Local checkpoint:

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 5c
```

See `docs/STAGE_05C_LOCAL_RUN.md` for the safe dry-run and explicit cloud build commands.

## Stage 5D — Master Data Warehouse Dimensions

Stage 5D adds governed product/branch/supplier master data to BigQuery and dbt dimensions for
Power BI. Product metadata remains explicitly sourced from the U.S. openFDA NDC catalog; pharmacy
and supplier identities remain explicitly synthetic. No price/revenue/cost/margin is generated.

```powershell
$env:PHARMSTOCK_BQ_MASTER_DATASET="pharmstock_master"
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 5d
```

See `docs/STAGE_05D_MASTER_DIMENSIONS.md` and `docs/STAGE_05D_LOCAL_RUN.md`.

## Stage 6A — Power BI serving layer

Stage 6A adds a dedicated `pharmstock_pbi` BigQuery serving dataset, a governed
star-schema semantic contract, a generated date dimension, explicit non-monetary DAX
measures, and a Power BI BigQuery ADBC v2 connection template. Cloud changes remain
guarded behind an explicit `--execute`.

### Stage 6B — Power BI Desktop

Stage 6B provides a source-controlled build kit for the first Power BI Desktop
semantic model and operational report. Run `scripts/run_checkpoint.py 6b` after
Stage 6A cloud deployment succeeds.

## Stage 7A — Egyptian Pharmaceutical Master / Production Expansion

Stage 7A starts the production-like data expansion. The future product baseline now uses a real,
public Egypt-market medicine snapshot with EGP retail prices and explicit source/license/hash
provenance. Regulatory fields remain pending until verified against the Egyptian Drug Authority;
no registration number, GTIN, license status, or official-price status is fabricated.

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 7a
```

Outputs include `egypt_product_master.csv`, `product_price_history.csv`, an EDA verification queue,
and a data-quality report. See `docs/STAGE_07A_EGYPTIAN_PHARMA_MASTER.md`.

## Stage 7B — Production Egyptian Pharmacy Network

Stage 7B expands the synthetic pharmacy side of the digital twin to a default 5,000 branches
across all 27 governorates. Allocation is calibrated to CAPMAS 2024 population and urban/rural
statistics and reconciles to a national reference scale of 86,741 general pharmacies. Generated
business identities remain explicitly fictional and `SYNTHETIC_CALIBRATED`.

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 7b
```

See `docs/STAGE_07B_PRODUCTION_PHARMACY_NETWORK.md`.

## Stage 7C — Production Pricing & Financial Engine

Stage 7C adds EGP financial completeness to the Egypt-oriented digital twin without blurring data
provenance: public-market retail prices remain observed inputs while acquisition cost, internal
margin, branch discount policy and payment mix are deterministic calibrated simulation values.
Tax is not decomposed or assigned a universal rate without a medicine-specific public source.
See `docs/STAGE_07C_PRODUCTION_FINANCIAL_ENGINE.md`.

## Stage 7D — On-Prem PostgreSQL Operational / POS Database

Stage 7D introduces a local PostgreSQL 18.6 operational source of record at `localhost:5433`.
It loads the Stage 7A Egyptian-market product/price master, the Stage 7B 5,000-branch network and
Stage 7C financial calibration, then exposes normalized POS/inventory/procurement schemas. Logical
WAL, a replication role and a `pgoutput` publication are prepared for the later Debezium CDC stage.
No replication slot is created yet.

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 7d
```

See `docs/STAGE_07D_ONPREM_POSTGRESQL.md` and `docs/STAGE_07D_LOCAL_RUN.md`.

## Stage 7E — High-Fidelity Historical POS & Operational Simulator

Stage 7E populates the Stage 7D PostgreSQL source of record with a deterministic, production-like
historical workload. The default acceptance profile spans 5,000 branches across all 27
governorates and creates million-scale POS sales plus fulfilled/partial/out-of-stock demand,
inventory and procurement records with calibrated supplier delays. Product identity and retail
price remain `PUBLIC_MARKET_EGYPT`; generated transactions and operational history are explicitly
`SYNTHETIC_CALIBRATED`. No customer PII is generated.

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 7e
```

See `docs/STAGE_07E_HISTORICAL_POS_SIMULATOR.md` and `docs/STAGE_07E_LOCAL_RUN.md`.


## Current checkpoint: Stage 7G

Stage 7G performs the controlled large-scale rebuild. Kafka high-watermark offsets are captured
before the PostgreSQL snapshot, Spark 4.2.0 exports the 26-table production-like history through
JDBC, and a second offset capture bounds an exact CDC catch-up range. Tables changed during the
cutover are reconciled by primary key; the end offsets become the resume point for later streaming.
The checkpoint creates BigQuery-ready Parquet and a deployment plan but performs no cloud mutation.

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 7g
```

See `docs/STAGE_07G_LARGE_SCALE_REBUILD.md` and `docs/STAGE_07G_LOCAL_RUN.md`.

## Current checkpoint: Stage 7H

Stage 7H is the explicit BigQuery + dbt deployment boundary for the accepted Stage 7G rebuild.
The normal checkpoint is a local-safe preflight and never mutates Google Cloud. The explicit cloud
runner stages all 26 Parquet tables, validates row counts and primary keys, promotes the raw rebuild
into `pharmstock_ops_rebuild`, then builds Stage 7H dbt staging/intermediate/Gold analytics.

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 7h
```

See `docs/STAGE_07H_BIGQUERY_DBT_DEPLOYMENT.md` and `docs/STAGE_07H_LOCAL_RUN.md`.

## Stage 7K.5 — Online ML Decision Runtime ✅
- CDC-triggered PostgreSQL read-through online features.
- Four production-gated Stage 7K champions behind the local serving API.
- Durable prediction journal/outbox and compacted ML decision topics.
- Docker healthcheck, malformed-event quarantine and bounded retry.
- No BigQuery write and no ML feedback into Debezium.

## Stage 7L — Governed Operational Decision Workflow
- Consumes stockout, reorder and expiry decision topics from Stage 7K.5.
- Bootstraps the latest non-smoke ML state, then resumes Kafka without a cold-start gap.
- Persists a durable inbox, quarantine, decision cases, evidence and audit trail.
- Converts reorder recommendations only into human-reviewable replenishment drafts.
- Uses a dedicated least-privilege database role with purchase-order writes revoked.
- Automatic supplier selection and automatic Purchase Order creation remain blocked.

## Stage 7M — Operational Decision API + Pharmacy Workbench
- Loopback-only governed API at `http://127.0.0.1:8091`.
- Pharmacy workbench at `/workbench` with viewer/operator/manager/admin RBAC.
- Stable decision read model plus summary, queue, detail and governed-action endpoints.
- Dedicated column-scoped PostgreSQL workbench role and append-only operational audit.
- No automatic supplier selection, Purchase Order endpoint, BigQuery write or cloud mutation.
