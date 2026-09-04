# PharmStock V2 — Visible Evolution Log

The original project remains read-only. These checkpoints document what V2 can actually
run after each stage.

| Checkpoint | What you can run locally | Visible result |
|---|---|---|
| Stage 0 | package/tests | project imports and base tests |
| Stage 1A | Product domain tests | validated medicine master-data contracts |
| Stage 1B | Pharmacy domain tests | validated organization/branch contracts |
| Stage 1C | `python scripts/run_checkpoint.py 1c` | one sale changes inventory and emits domain events |
| Stage 2A | `python scripts/run_checkpoint.py 2a` | a generated multi-governorate pharmacy network and CSV/JSON files |
| Stage 2B | `python scripts/run_checkpoint.py 2b` | official openFDA records normalized into package-level SKUs |
| Stage 2C | `python scripts/run_checkpoint.py 2c` | real catalog + pharmacy network joined into assortment, stock and expiry batches |
| Stage 2D | `python scripts/run_checkpoint.py 2d` | partitioned bounded-memory inventory export + FEFO batch allocation |
| Stage 2E | `python scripts\run_checkpoint.py 2e` | 7-day structured unit demand -> FEFO sales -> stockouts/reorders -> ending stock |
| Stage 2F | `python scripts\run_checkpoint.py 2f` | low stock -> six-supplier learning checkpoint -> PO -> delivery -> replenished stock |
| Stage 2F.1 | `python scripts\run_checkpoint.py 2f1` | 153-supplier ecosystem -> branch panel -> ranked supplier allocation -> utilization |

## Stage 1C -> Stage 2A

Before:

```text
one explicit branch
    +
one explicit inventory item
    -> sale / restock / event behavior
```

Now:

```text
real Egyptian governorate population weights
    -> synthetic organizations
    -> configurable branch count
    -> validated PharmacyBranch objects
    -> inspectable CSV/JSON artifacts
```

Future stages must add their own row and runnable checkpoint here.


## Stage 2B — Real Drug Catalog
- Live official openFDA NDC ingestion.
- Raw source retention and rejection quarantine.
- Package-level canonical drug SKUs.
- Deterministic product IDs and source lineage.
- Visible local checkpoint: `python scripts\run_checkpoint.py 2b`.


## Stage 2C — Branch Assortment + Initial Inventory
- Joins the Stage 2A network with the Stage 2B canonical catalog.
- Enforces SKU-capacity and physical storage-capacity constraints.
- Generates reorder policies and simulated batch/expiry rows.
- Explicitly labels the US-catalog / Egyptian-network join as synthetic cross-market mapping.
- Does not invent market prices.
- Visible local checkpoint: `python scripts\run_checkpoint.py 2c`.

## Stage 2D — Scale Hardening + FEFO
- Adds one-branch-at-a-time inventory generation for bounded-memory export.
- Writes partitioned inventory and batch CSV files plus an explicit manifest.
- Adds immutable batch-domain models and FEFO allocation.
- Expired batches are excluded from sale allocation.
- Keeps Stage 2C as an inspectable in-memory learning checkpoint; Stage 2D is the scalable path.
- Visible local checkpoint: `python scripts\run_checkpoint.py 2d`.


## Stage 2E — Structured Demand + Unit Sales
- Replays multi-day synthetic demand against the completed Stage 2D inventory dataset.
- Uses branch scale/type, opening hours, weekday/hour effects, long-tail product popularity, and explicitly synthetic seasonality cohorts.
- Fulfills sellable units through FEFO and records lost demand when stock cannot satisfy the request.
- Writes partitioned demand lines, FEFO allocations, stock movements, reorder triggers, ending inventory/batches, and daily branch KPIs.
- Generates no prices or revenue; the current demand model is synthetic and clearly labeled as such.
- Keeps one branch state in memory at a time.
- Visible local checkpoint: `python scripts\run_checkpoint.py 2e`.


## Stage 2F — Procurement + Replenishment
- Starts after the completed Stage 2E demand window, preserving temporal consistency.
- Converts end-of-cycle low-stock state into supplier-grouped Purchase Orders.
- Uses clearly labeled synthetic supplier identities and lead times.
- Applies physical storage-capacity limits and records deferred units in a procurement backlog.
- Converts deliveries into new batches and positive restock stock movements.
- Generates no prices, costs, revenue or profit.
- Visible local checkpoint: `python scripts\run_checkpoint.py 2f`.


## Stage 2F.1 — Supplier Network Scaling
- Preserves Stage 2F as the six-supplier learning checkpoint.
- Adds a deterministic 153-supplier fictional ecosystem: national, regional, local, direct-manufacturer and cold-chain archetypes.
- Gives each branch a preferred panel of 12 geographically valid suppliers.
- Ranks product sourcing by geography, catalog coverage, reliability, expected fill rate, lead time and remaining cycle capacity.
- Exports supplier utilization and active-supplier counts for BI/data-engineering inspection.
- Keeps all supplier identities and metrics explicitly synthetic and non-monetary.
- Visible local checkpoint: `python scripts\run_checkpoint.py 2f1`.

## Stage 3A — Kafka Foundation

A local Apache Kafka broker transports one validated PharmStock domain event end-to-end.

## Stage 3B — Simulator Event Streaming
- Converts completed Stage 2E and Stage 2F.1 artifacts into replay-stable versioned Kafka events.
- Streams physical unit sales, inventory changes, reorders, purchase orders, goods receipts and restocks.
- Uses deterministic UUID5 event IDs so a replay does not silently invent new identities.
- Batches producer writes and keeps replay bounded by artifact partitions.
- Adds a Kafka dead-letter producer; validated checkpoint artifacts should produce zero DLQ records.
- Keeps money/pricing outside the event stream because those values are not yet authoritative.
- Visible local checkpoint: `python scripts\run_checkpoint.py 3b`.

## Stage 3C — Durable Consumer Processing + Idempotency
- Adds a SQLite durable inbox ledger keyed by `event_id`.
- Records source Kafka topic/partition/offset and a SHA-256 hash of the canonical validated event.
- Replayed copies with the same `event_id` and same canonical content are recorded as duplicates and are not processed twice.
- Reusing one `event_id` for different validated content is an explicit idempotency conflict, not a silent duplicate.
- Invalid payloads and application-handler failures are persisted in a failure ledger and published to `pharmstock.dead-letter.v1` before the source offset is committed.
- Source offsets are committed only after one durable outcome: processed, duplicate, or failed+DLQ.
- The delivery contract is intentionally described as Kafka at-least-once + application inbox deduplication; it does not claim distributed exactly-once semantics across Kafka, SQLite, and arbitrary external sinks.
- Visible local checkpoint: `python scripts\run_checkpoint.py 3c`.


## Stage 4A — Spark Structured Streaming Foundation
- Adds Apache Spark 4.2.0 in a pinned Docker runtime rather than bloating the application virtualenv.
- Adds a Kafka Docker listener (`kafka:19092`) while preserving `localhost:9092` for Windows clients.
- Reads the three operational Kafka topics with Structured Streaming and `Trigger.AvailableNow`.
- Validates the common versioned event envelope and preserves raw JSON/payload in Bronze Parquet.
- Routes malformed or envelope-invalid records to a Parquet quarantine dataset with a validation reason.
- Retains Kafka `(topic, partition, offset)` as the immutable Bronze source identity.
- Uses Spark checkpointing plus deterministic per-batch output paths so successful offsets are not replayed after restart.
- Preserves repeated domain `event_id` records in Bronze; event-level deduplication is deferred to Silver.
- Visible local checkpoint: `python scripts/run_checkpoint.py 4a`.

## Stage 4B — Silver Parsing + Deduplication + Normalization
- Reads Stage 4A Bronze Parquet with Spark 4.2.0.
- Applies `event_id` deduplication while preserving exact replay copies in an audit dataset.
- Detects same-`event_id` semantic conflicts instead of silently choosing one payload.
- Excludes only `recorded_at` from semantic equality so replay observation time does not create false conflicts.
- Revalidates each event-specific V1 payload and sends invalid payloads to a Silver reject dataset.
- Writes six typed Silver event tables plus a common event index with Kafka lineage.
- Reconciles every Bronze row to Silver, duplicate, conflict, or reject.
- Uses deterministic local full refresh as the inspectable foundation for later BigQuery/dbt incremental models.
- Visible local checkpoint: `python scripts\run_checkpoint.py 4b`.


## Stage 5A — BigQuery Warehouse Foundation
- Adds seven explicit BigQuery table contracts: six normalized facts plus `event_index`.
- Validates actual Stage 4B Silver columns/types with Spark 4.2.0 before warehouse handoff.
- Rewrites Parquet so `event_date` is materialized in each file for direct local-file loading.
- Keeps Kafka lineage and semantic hashes intact; no monetary values are invented.
- Generates BigQuery schema JSON, dataset/table DDL, a warehouse catalog, and a dry-run load plan.
- Keeps cloud mutation out of the default checkpoint; the optional BigQuery loader requires
  explicit project/auth plus `--execute --replace`.
- Pins the optional Google BigQuery Python client to `google-cloud-bigquery==3.43.0`.
- Visible local checkpoint: `python scripts\run_checkpoint.py 5a`.


## Stage 5B — Real BigQuery Cloud Integration
- Adds a cloud-safe readiness checkpoint that never mutates GCP.
- Uses ADC for the explicit live path; secrets are never embedded in the repository.
- Loads local Parquet into run-scoped staging tables before target promotion.
- Verifies staging rows, final rows, schema, partitioning and clustering.
- Promotes verified staging data with `CREATE OR REPLACE TABLE` and explicit `NOT NULL` contract, then cleans staging.
- Visible local checkpoint: `python scripts\run_checkpoint.py 5b`.


## Stage 5C — dbt Analytics / Gold Layer

Adds dbt Core/dbt-bigquery over the verified Stage 5B Silver warehouse, with layered staging, ephemeral intermediate transformations, seven Gold/Power BI-ready models, dbt tests, lineage metadata, and explicit no-monetary-fabrication controls.


## Stage 5D — Master dimensions

The analytics warehouse now has an explicit `pharmstock_master` layer feeding dbt dimensions
`dim_product`, `dim_branch`, and `dim_supplier`. Product origin is U.S. openFDA; pharmacy and
supplier entities remain synthetic and are labeled as such.

## Stage 6A — Power BI serving layer (v0.20.0)
- Dedicated `pharmstock_pbi` BigQuery serving boundary.
- 11 governed Power BI views including a generated date dimension.
- 17 one-to-many, single-direction semantic relationships.
- 18 explicit non-monetary DAX measures.
- BigQuery ADBC v2 connection template and Import-first guidance.
- Local-safe checkpoint and explicit guarded cloud deployment.

## Stage 6B — Power BI Desktop build kit (v0.21.0)

Adds a deterministic Desktop semantic-model/report build manifest, relationship
and measure checklists, DAX library, report-page specification, and an explicit
manual acceptance boundary for PBIX/PBIP authoring.

## Stage 7A — Egyptian Pharmaceutical Master (v0.22.0)
- Begins the production-scale expansion after proving the end-to-end BigQuery/Power BI path.
- Replaces the future product-master baseline from U.S. openFDA metadata to a real/public
  Egypt-market snapshot released under CC0.
- Keeps the source truth boundary explicit: public market observations are
  `PUBLIC_MARKET_EGYPT`, not `OFFICIAL_EGYPT`.
- Adds positive EGP retail price observations with snapshot provenance and deterministic IDs.
- Excludes obvious cancelled / not-yet-available / illegal-import markers from the active medicine
  candidate master while retaining them in an audit file.
- Requires scientific composition for promotion into the medicine master.
- Generates an EDA verification queue for registration number, GTIN, license status, price status,
  and registration expiry instead of fabricating regulatory fields.
- Records source SHA-256 and license metadata for reproducible ingestion.
- Does not bypass EDDB verification-code controls and performs no cloud mutation.
- Visible checkpoint: `python scripts/run_checkpoint.py 7a`.

## Stage 7B — Production Egyptian Pharmacy Network (v0.23.0)
- Expands the production-like pharmacy network to a default 5,000 branches.
- Covers all 27 Egyptian governorates in every production profile.
- Anchors allocation to CAPMAS 2024 population and urban/rural shares.
- Uses the CAPMAS 2024 national reference of 86,741 general pharmacies as the full-market scale.
- Keeps all branch identities, ownership, locality codes, capacities and operating traits explicitly
  `SYNTHETIC_CALIBRATED`.
- Adds `dev=27`, `acceptance=5,000`, and `full_market=86,741` profiles.
- Adds branch expansion weights for deliberate national-scale estimation without pretending the
  5,000 modeled branches are real establishments.
- Adds national/governorate calibration, reproducible generation, quality reports and source links.
- Performs no cloud mutation.
- Visible checkpoint: `python scripts/run_checkpoint.py 7b`.

### Stage 7B lint hotfix — v0.23.1

- Ruff-only source hygiene fix: deterministic import ordering in `simulation/__init__.py`.
- `Iterable` now imports from `collections.abc`.
- No network generation, calibration, provenance, or acceptance semantics changed.

## Stage 7C — Production Pricing & Financial Engine (v0.24.0)
- Carries 22k+ EGP retail-price observations from the Egyptian-market master without changing provenance.
- Adds deterministic `SYNTHETIC_CALIBRATED` purchase cost and gross-margin economics per product.
- Adds per-branch commercial policies for discount ceilings, shrinkage reserves and payment mix.
- Adds a reusable sale-line financial contract for Revenue, COGS and Gross Profit reconciliation.
- Explicitly refuses to infer a universal medicine tax/VAT rate from insufficient public evidence.
- Produces auditable assumptions and quality reports; performs no cloud mutation.
- Visible checkpoint: `python scripts\run_checkpoint.py 7c`.

## Stage 7D — On-Prem PostgreSQL Operational / POS Database (v0.25.0)
- Introduces PostgreSQL 18.6 as the local operational source-of-record database.
- Seeds the accepted Stage 7A Egyptian-market product/price snapshot, Stage 7B 5,000-branch
  production digital twin, and Stage 7C product/branch commercial calibration.
- Adds normalized POS, inventory and procurement transaction schemas suitable for direct service
  writes rather than CSV-first transaction generation.
- Adds deterministic POS terminals from each branch's checkout capacity.
- Uses staging-only truncation plus idempotent target upserts so master refreshes do not destroy
  later operational transactions.
- Enables logical WAL, SCRAM authentication, replication slots/senders and a dedicated CDC role.
- Pre-creates a 13-table `pgoutput` publication but deliberately creates no Debezium slot yet.
- Adds database-level financial reconciliation, PK/FK, inventory and provenance constraints.
- Performs local Docker/PostgreSQL mutation only; no cloud mutation.
- Visible checkpoint: `python scripts/run_checkpoint.py 7d`.

## Stage 7E — High-Fidelity Historical POS & Operational Simulator (v0.26.0)
- Generates deterministic historical POS operations directly inside PostgreSQL rather than CSV fixtures.
- Default acceptance workload covers 5,000 branches and 14 historical days across all 27 governorates.
- Uses branch demand indices, Egypt Friday/Saturday weekend effects, branch opening hours, service modes,
  checkout capacity, branch payment mix and discount ceilings.
- Generates long-tail product demand over the Stage 7A Egypt-market catalog while preserving observed
  retail-price provenance and calibrated internal costs separately.
- Adds financially reconciled sale headers/lines, payments, explicit demand/lost-demand attempts and
  low-rate quarantine returns.
- Adds opening stock batches, inventory positions, opening receipt movements and one sale stock movement
  per sale line.
- Adds a 300-supplier calibrated opening-procurement history with POs, PO lines, goods receipts,
  receipt lines and deterministic 0–5 day supplier delays for future delay-risk ML labels.
- Generates no customer PII.
- Keeps Debezium/replication-slot deployment deferred to Stage 7F; the new `pos.demand_attempt`
  table is intentionally added to the CDC publication in that stage rather than mutating Stage 7D's
  accepted 13-table publication contract here.
- Provides a guarded 365-day `prod_like` profile for tens-of-millions transaction scale.
- Visible checkpoint: `python scripts/run_checkpoint.py 7e`.

## Stage 7E correction — Fast resumable audit + customer digital twin (v0.26.1)

- Replaced the blocking full operational-table audit with fast staging metrics.
- Commit-before-finalize makes Stage 7E resumable after an interrupted audit.
- Added privacy-safe customer, household, loyalty, patient and prescription simulation.
- Linked known/anonymous customer behavior into POS while preserving explicit provenance.

## Stage 7K.5 — Online ML Decision Runtime
- Converts new operational CDC changes into read-through features and four production-gated model
  decisions without replaying historical CDC.
- Persists prediction events and a transactional outbox before publishing compacted ML decision
  streams.
- Adds real Docker health, durable poison-message quarantine and bounded retry.

## Stage 7L — Governed Operational Decision Workflow
- Consumes only the actionable stockout, reorder and expiry decision streams.
- Cold-starts from the latest non-smoke ML journal while protecting the Kafka bootstrap watermark.
- Persists a durable decision inbox, quarantine, active cases, model evidence and audit history.
- Converts reorder output to a replenishment draft only; supplier selection and Purchase Order
  creation are blocked by both workflow policy and PostgreSQL privileges.

## Stage 7M — Operational Decision API + Pharmacy Workbench (v0.37.0)
- Adds a loopback-only FastAPI boundary for governed Stage 7L cases.
- Adds viewer/operator/manager/admin API-key RBAC with deny-by-default action authorization.
- Adds `decision_ops.v_case_workbench` as a stable operational read model.
- Uses a dedicated `pharmstock_workbench` role with column-scoped workflow update privileges.
- Makes the operational decision audit append-only at the PostgreSQL permission boundary.
- Adds a browser workbench plus summary/case/detail/action endpoints.
- Exposes no supplier-selection, Purchase Order, Goods Receipt, or procurement execution endpoint.
- Performs no BigQuery write or cloud mutation.

## Stage 7N — Power BI Production Semantic & Serving Layer (v0.38.0)

- Replaces the old pre-rebuild Stage 6A semantic boundary for the current 31.9M-row architecture.
- Adds `pharmstock_pbi_prod` as a metadata-only BigQuery view dataset over Stage 7H Gold and Stage
  7I current-state views.
- Adds PostgreSQL `bi` views for Stage 7K.5 ML state and Stage 7L/7M governed decisions.
- Adds a dedicated read-only `pharmstock_bi` role with no procurement/ML/decision write path.
- Generates a 14-table semantic contract, 24 measures and five report-page specifications.
- Preserves truth-boundary labels for public-market retail prices and synthetic-calibrated costs.
