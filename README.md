# 💊 PharmStock AI Platform V2

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-pharmstock-ai-platform-v2)

### End-to-End Data Engineering, MLOps & Governed AI for Pharmacy Operations

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#end-to-end-data-engineering-mlops--governed-ai-for-pharmacy-operations)

[Python](https://camo.githubusercontent.com/530421a6185b633272b9db7dec226037bf4ff29108c7bbbbbedc4244c6b93b92/68747470733a2f2f696d672e736869656c64732e696f2f62616467652f507974686f6e2d332e782d626c7565) [Docker](https://camo.githubusercontent.com/9b0bdffbb1bccd0e822112f972496773c36d76f75d11e2946971cf31980e232d/68747470733a2f2f696d672e736869656c64732e696f2f62616467652f446f636b65722d436f6e7461696e6572697a65642d323439364544) [Kafka](https://camo.githubusercontent.com/44affe23a5e145af8ba89b8067c2445d765dd80809f43a128cf64805b44a7380/68747470733a2f2f696d672e736869656c64732e696f2f62616467652f4170616368652532304b61666b612d43444325323053747265616d696e672d626c61636b) [Spark](https://camo.githubusercontent.com/359c28670657174403299b15caf753676abf75455abf3a95be4c42038f880171/68747470733a2f2f696d672e736869656c64732e696f2f62616467652f417061636865253230537061726b2d446973747269627574656425323050726f63657373696e672d6f72616e6765) [BigQuery](https://camo.githubusercontent.com/f7853b6d009a7a61c3c9d2da9c5cef862424aed2fffc6a51b4158b22651d0a14/68747470733a2f2f696d672e736869656c64732e696f2f62616467652f476f6f676c6525323042696751756572792d436c6f756425323057617265686f7573652d343238354634) [MLflow](https://camo.githubusercontent.com/82cd690e6a3f6023730adaf5325c20651f29a982395ec40fde91a417a76153e5/68747470733a2f2f696d672e736869656c64732e696f2f62616467652f4d4c666c6f772d4d6f64656c25323052656769737472792d303139344532) [Airflow](https://camo.githubusercontent.com/a9fb34184388cfd3335f3a2d1892db18c5c93306e3dc37f715b25ebbe07a002a/68747470733a2f2f696d672e736869656c64732e696f2f62616467652f417061636865253230416972666c6f772d4f726368657374726174696f6e2d303137434545) [Power BI](https://camo.githubusercontent.com/1690f53d831098688cdbcdc97c3cd2726010f6418046d87dd9f3b3410e76a94c/68747470733a2f2f696d672e736869656c64732e696f2f62616467652f506f77657225323042492d427573696e657373253230496e74656c6c6967656e63652d463243383131)

**CDC Streaming • Large-Scale Data Engineering • MLOps • Online ML • Human-in-the-Loop Decisions • Governed AI • Business Intelligence**

---

## 🚀 Overview

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-overview)

**PharmStock AI Platform V2** is an end-to-end data engineering and AI platform designed around pharmacy inventory and operational decision-making.

The project demonstrates how transactional data can move through a modern production-oriented architecture — from **Change Data Capture (CDC)** and distributed processing to cloud analytics, machine learning, governed operational workflows, AI-assisted investigation, and executive reporting.

The end-to-end flow is:

```
PostgreSQL
    ↓
Debezium CDC
    ↓
Apache Kafka
    ↓
Apache Spark
    ↓
Google BigQuery
    ↓
dbt + Apache Airflow
    ↓
ML Training + MLflow Registry
    ↓
Online Model Serving
    ↓
Governed Decision Workflow
    ↓
Operational Workbench + Governed AI Assistant
    ↓
Power BI

```

**svg**

This is not a notebook-only ML project or a standalone BI dashboard.

The repository implements a connected platform where **data engineering, analytics engineering, MLOps, operational governance, AI assistance, and BI are integrated into one architecture**.

> **Data transparency:** Operational data presented by the platform is synthetic/calibrated and is used for production-style simulation. It does not represent live pharmacy operations.

---

## 📑 Table of Contents

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-table-of-contents)

- [Overview](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-overview)
- [Platform Objectives](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-platform-objectives)
- [System Architecture](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-system-architecture)
- [Platform Layers](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-platform-layers)
- [Governed AI Assistant](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-governed-ai-assistant--stage-7o)
- [Operational Decision Workbench](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-operational-decision-workbench--stage-7m)
- [Data Engineering Pipeline](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-data-engineering-pipeline)
- [Cloud Analytics Layer](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-cloud-analytics-layer)
- [Orchestration, Data Quality & Monitoring](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-orchestration-data-quality--monitoring)
- [Machine Learning Layer](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-machine-learning-layer)
- [MLOps with MLflow](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-mlops-with-mlflow)
- [Online ML & Model Serving](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-online-ml--model-serving)
- [Governance & Human-in-the-Loop Design](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-governance--human-in-the-loop-design)
- [Business Intelligence](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-business-intelligence--power-bi)
- [Technology Stack](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-technology-stack)
- [Engineering Highlights](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-engineering-highlights)
- [Repository Structure](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-repository-structure)
- [Running the Platform](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-running-the-platform)
- [Validation Philosophy](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-validation-philosophy)
- [Security & Responsible AI](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-security--responsible-ai)
- [Data & Deployment Disclaimer](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-data--deployment-disclaimer)

## 🎯 Platform Objectives

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-platform-objectives)

PharmStock V2 was designed to address several engineering problems within one system:

- 🔄 Capture operational database changes through **CDC**
- ⚡ Process historical and streaming workloads at scale
- ☁️ Build cloud analytical datasets and curated business models
- 🧪 Apply automated data-quality and operational health checks
- 🤖 Train and manage multiple operational ML models
- 🚀 Serve promoted models for online inference
- 🧠 Convert ML signals into actionable decision cases
- 🛡️ Enforce human approval and role-based operational controls
- 💬 Provide grounded AI assistance with provenance
- 📊 Deliver executive and operational analytics through Power BI

---

# 🏗️ System Architecture

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#%EF%B8%8F-system-architecture)

PharmStock V2 follows a layered architecture that separates ingestion, processing, analytics, machine learning, decision governance, AI assistance, and business consumption.

**svgsvg**

[File display](https://viewscreen.githubusercontent.com/markdown/mermaid?docs_host=https%3A%2F%2Fdocs.github.com\&color_mode=dark#f1fad728-50c6-42a0-9a42-02b51a317cc9)

### Architecture Principles

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#architecture-principles)

The platform was built around several core engineering principles:

**Event-driven ingestion**
Operational changes are captured through Debezium and propagated through Kafka rather than relying only on batch extraction.

**Historical + incremental processing**
Spark supports large-scale historical reconstruction while CDC protects the transition to incremental processing.

**Separation of analytical layers**
Raw operational history, current-state representations, and curated analytical models are separated rather than mixed into one storage layer.

**Model lifecycle management**
ML models are tracked and registered through MLflow before being promoted into the serving layer.

**Prediction is not execution**
A model prediction does not directly trigger a business action. Predictions enter a governed decision workflow.

**Human-in-the-loop governance**
Operational actions such as approving replenishment drafts remain explicitly controlled.

**Grounded AI**
The AI assistant operates through governed evidence and provenance rather than unrestricted direct access to operational systems.

---

# 🧱 Platform Layers

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-platform-layers)

| **LayerTechnologiesResponsibility** |                          |                                                   |
| ----------------------------------- | ------------------------ | ------------------------------------------------- |
| **Operational Source**              | PostgreSQL               | Transactional pharmacy data                       |
| **CDC**                             | Debezium                 | Capture database changes                          |
| **Event Streaming**                 | Apache Kafka             | Durable event transport                           |
| **Distributed Processing**          | Apache Spark             | Historical rebuild and incremental processing     |
| **Cloud Warehouse**                 | Google BigQuery          | Analytical storage and current-state datasets     |
| **Analytics Engineering**           | dbt                      | Curated analytical transformations                |
| **Orchestration**                   | Apache Airflow           | Scheduling, DQ and operational monitoring         |
| **MLOps**                           | MLflow                   | Experiment tracking, registry and model promotion |
| **Model Serving**                   | Python / API Services    | Online inference                                  |
| **Decision Governance**             | Governed Workflow + RBAC | Controlled operational actions                    |
| **AI Assistance**                   | Governed AI Assistant    | Evidence-grounded operational investigation       |
| **Business Intelligence**           | Power BI                 | Executive and operational reporting               |

---

# 🧠 Governed AI Assistant — Stage 7O

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-governed-ai-assistant--stage-7o)

The **Governed AI Assistant** is positioned at the operational decision layer rather than being given unrestricted access to the platform.

It can investigate governed operational evidence while preserving explicit safety boundaries.

### Key capabilities

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#key-capabilities)

- 🔎 Stockout-risk investigation
- 📦 Operational inventory context
- 🤖 ML signal interpretation
- 🧾 Evidence provenance
- 🔗 Operational and reference evidence tracking
- 🛡️ Governance-aware responses
- 👤 Human-controlled operational actions

### Explicit governance boundaries

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#explicit-governance-boundaries)

The assistant is intentionally prevented from:

- accessing the operational database directly
- mutating operational data
- selecting suppliers automatically
- creating purchase orders automatically

[Stage 7O Governed AI Assistant](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/docs/assets/screenshots/stage7o-governed-ai-assistant.png) ([image](https://github.com/ayadigiliansDE/pharmstock-ai-platform/raw/main/docs/assets/screenshots/stage7o-governed-ai-assistant.png))

*Governed investigation of stockout risk with evidence provenance and operational safety boundaries.*

---

# 🛡️ Operational Decision Workbench — Stage 7M

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#%EF%B8%8F-operational-decision-workbench--stage-7m)

ML predictions are converted into governed operational cases rather than directly executed.

The **Stage 7M Operational Decision Workbench** provides the human decision surface for reviewing those cases.

### Governance model

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#governance-model)

The workbench implements:

- 🔐 API-key authentication
- 👥 Role-Based Access Control (RBAC)
- 👁️ Viewer access
- ⚙️ Operator actions
- 🧑‍💼 Manager approval controls
- 🛡️ Administrative privileges
- 📝 Governed case lifecycle
- ✅ Draft approval
- ❌ Controlled rejection
- 📋 Operational auditability

The workflow follows the principle:

> **Prediction → Decision Case → Human Review → Governed Action**

rather than:

> **Prediction → Automatic Business Action**

[Stage 7M Operational Decision Workbench](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/docs/assets/screenshots/stage7m-governed-operational-decision-workbench.png) ([image](https://github.com/ayadigiliansDE/pharmstock-ai-platform/raw/main/docs/assets/screenshots/stage7m-governed-operational-decision-workbench.png))

*Human-in-the-loop operational workbench with governed case actions and role-based controls.*

---

# ⚙️ Data Engineering Pipeline

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#%EF%B8%8F-data-engineering-pipeline)

The data engineering layer is responsible for moving operational pharmacy data from transactional storage into scalable analytical and machine-learning workloads.

## 1. PostgreSQL — Operational Source

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#1-postgresql--operational-source)

PostgreSQL represents the transactional pharmacy system and provides the source data for the platform.

The operational domain includes entities related to:

- products
- inventory
- branches
- sales
- suppliers
- purchasing
- stock movements
- operational reference data

The platform preserves the operational database as the transactional source while downstream components consume changes through controlled ingestion paths.

---

## 2. Debezium — Change Data Capture

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#2-debezium--change-data-capture)

Instead of repeatedly extracting complete operational tables, **Debezium CDC** captures database-level changes from PostgreSQL.

```
INSERT
UPDATE
DELETE
   │
   ▼
PostgreSQL WAL
   │
   ▼
Debezium
   │
   ▼
Kafka Topics

```

**svg**

This enables the platform to maintain an event-driven representation of operational changes while reducing dependence on repeated full-table batch extraction.

---

## 3. Apache Kafka — Event Streaming

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#3-apache-kafka--event-streaming)

Kafka provides the durable event transport layer between CDC ingestion and downstream processing.

The platform uses dedicated CDC topics to isolate operational change streams and support incremental processing.

### Kafka responsibilities

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#kafka-responsibilities)

- durable CDC event transport
- decoupling producers from consumers
- ordered processing within partitions
- replayable event history
- scalable downstream consumption

---

## 4. Apache Spark — Historical & Incremental Processing

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#4-apache-spark--historical--incremental-processing)

Spark handles the distributed processing layer.

The platform supports two complementary workloads:

### Historical reconstruction

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#historical-reconstruction)

Existing PostgreSQL data can be rebuilt into analytical storage without replaying the entire historical dataset through Kafka.

### Incremental CDC processing

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#incremental-cdc-processing)

After the historical snapshot boundary, new CDC events can be processed incrementally.

This design protects the cutover between:

```
Historical State
       +
CDC Changes
       ↓
Consistent Analytical State

```

**svg**

The historical rebuild implementation covers **26 snapshot tables and 13 CDC topics**, with explicit cutover-gap protection and a BigQuery-ready rebuild path.

---

# ☁️ Cloud Analytics Layer

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#%EF%B8%8F-cloud-analytics-layer)

## Google BigQuery

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#google-bigquery)

BigQuery provides the analytical warehouse for the cloud-facing portion of PharmStock V2.

The warehouse design separates different responsibilities rather than treating all data as one flat analytical dataset.

```
Operational Source
       ↓
Raw / Historical Data
       ↓
Current-State Representations
       ↓
Curated Analytical Models
       ↓
ML / BI / Operational Analytics

```

**svg**

The platform maintains **26 raw tables, 26 current-state views, and curated gold models** while validating CDC integrity and analytical consistency.

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#the-platform-maintains-26-raw-tables-26-current-state-views-and-curated-gold-models-while-validating-cdc-integrity-and-analytical-consistency)

## dbt — Analytics Engineering

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#dbt--analytics-engineering)

dbt is used to transform warehouse data into governed analytical models.

Its role includes:

- SQL-based transformations
- modular analytical modeling
- reusable business logic
- model dependency management
- testable transformation workflows
- curated datasets for downstream consumers

This creates a clean separation between raw ingestion and business-facing analytical logic.

---

# 🔄 Orchestration, Data Quality & Monitoring

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-orchestration-data-quality--monitoring)

Apache Airflow coordinates recurring operational and analytical workflows.

The orchestration layer covers:

- pipeline scheduling
- health verification
- data-quality checks
- dependency coordination
- demand refresh workflows
- reconciliation workflows
- operational monitoring

The implemented data-quality layer validates conditions such as:

- expected raw table availability
- baseline row counts
- current-state views
- gold analytical models
- duplicate CDC events
- CDC event-store readability
- Debezium connector health
- BigQuery storage guardrails

A validated Stage 7J execution reported **zero duplicate CDC event rows**, all **26 current-state views**, and a healthy Debezium connector.

[PharmStock Apache Airflow DAG Orchestration](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/docs/assets/screenshots/airflow-pharmstock-dags-orchestration.png) ([image](https://github.com/ayadigiliansDE/pharmstock-ai-platform/raw/main/docs/assets/screenshots/airflow-pharmstock-dags-orchestration.png))

*Airflow orchestration for platform health, demand reconciliation, and demand refresh workflows.*

---

# 🤖 Machine Learning Layer

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-machine-learning-layer)

PharmStock V2 includes multiple operational machine-learning models rather than a single isolated prediction task.

## Operational Models

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#operational-models)

| **ModelOperational Purpose**  |                                                       |
| ----------------------------- | ----------------------------------------------------- |
| **Demand Forecast**           | Estimate future product demand                        |
| **Stockout Risk**             | Identify inventory positions at risk of stockout      |
| **Reorder Recommendation**    | Support replenishment decision-making                 |
| **Expiry / Slow-Moving Risk** | Identify inventory exposed to expiry or slow movement |

The models form part of the operational pipeline and feed downstream governed decision processes.

---

# 🧪 MLOps with MLflow

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-mlops-with-mlflow)

MLflow manages the model lifecycle.

The implementation includes:

- experiment tracking
- training runs
- model artifacts
- model registration
- model versioning
- model comparison
- quality gates
- champion aliases
- controlled model promotion

The serving layer currently validates **4 loaded models and 4 production-ready models** under a strict quality gate.

## 🏆 Champion Model Registry

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-champion-model-registry)

Promoted models are maintained through the MLflow Model Registry.

[PharmStock MLflow Registered Champion Models](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/docs/assets/screenshots/mlflow-registered-models-champion-registry.png) ([image](https://github.com/ayadigiliansDE/pharmstock-ai-platform/raw/main/docs/assets/screenshots/mlflow-registered-models-champion-registry.png))

*Registered operational ML models with versioning and champion aliases.*

This provides an explicit lifecycle:

```
Training
   ↓
Evaluation
   ↓
Quality Gate
   ↓
MLflow Registry
   ↓
Champion Promotion
   ↓
Model Serving

```

**svg**

---

# ⚡ Online ML & Model Serving

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-online-ml--model-serving)

Promoted models are loaded into a dedicated serving layer for operational inference.

The serving architecture separates:

```
Model Training
      ↓
Model Registry
      ↓
Model Serving
      ↓
Online ML Worker
      ↓
Operational Prediction
      ↓
Governed Decision Case

```

**svg**

This prevents model training logic from being directly coupled to operational decision execution.

The online ML worker operates as a separate runtime component and maintains its own health state.

---

# 🔐 Governance & Human-in-the-Loop Design

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-governance--human-in-the-loop-design)

Governance is a first-class architectural component of PharmStock V2.

The system deliberately separates:

```
Prediction
    ↓
Recommendation
    ↓
Decision Case
    ↓
Human Review
    ↓
Approval / Rejection
    ↓
Controlled Operational Action

```

**svg**

## RBAC

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#rbac)

Stage 7M implements four operational roles:

| **RoleIntended Responsibility** |                                               |
| ------------------------------- | --------------------------------------------- |
| **Viewer**                      | Read operational cases                        |
| **Operator**                    | Operational acknowledgement and case handling |
| **Manager**                     | Higher-authority review and approval          |
| **Admin**                       | Administrative operational authority          |

Authorization follows a **deny-by-default** approach.

## Safety Boundaries

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#safety-boundaries)

The platform intentionally blocks uncontrolled automation in sensitive procurement operations.

Examples include:

- automatic purchase-order creation is disabled
- automatic supplier selection is disabled
- AI direct database access is disabled
- AI operational mutations are blocked
- human approval remains required for governed actions

These controls are architectural decisions rather than UI-only restrictions.

---

# 📊 Business Intelligence — Power BI

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-business-intelligence--power-bi)

Power BI provides the final analytical and operational consumption layer.

The report combines traditional business KPIs with ML and governed-decision information.

## Executive Operations

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#executive-operations)

The executive view provides consolidated visibility into:

- net sales
- demand
- fill rate
- lost units
- inventory exposure
- reorder requirements
- expiry risk
- sales trends
- branch-level performance

[PharmStock Power BI Executive Operations Dashboard](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/docs/assets/screenshots/powerbi-executive-operations-dashboard.png) ([image](https://github.com/ayadigiliansDE/pharmstock-ai-platform/raw/main/docs/assets/screenshots/powerbi-executive-operations-dashboard.png))

*Executive pharmacy operations view covering sales, demand, inventory and risk.*

---

## 🤖 AI & Decision Operations

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-ai--decision-operations)

The AI & Decision Operations page connects machine-learning outputs with governed operational workflows.

It exposes:

- ML predictions
- critical ML signals
- decision cases
- actionable predictions
- decision acceptance
- human approval
- operational governance
- replenishment drafts
- detailed prediction context

[PharmStock Power BI AI and Decision Operations](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/docs/assets/screenshots/powerbi-ai-decision-operations.png) ([image](https://github.com/ayadigiliansDE/pharmstock-ai-platform/raw/main/docs/assets/screenshots/powerbi-ai-decision-operations.png))

*Integrated ML, human approval, decision governance, and operational monitoring.*

---

# 🐳 Containerized Runtime

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-containerized-runtime)

The platform is packaged as a multi-service Docker environment.

Core runtime services include:

```
PostgreSQL
Kafka
Debezium / Kafka Connect
Spark
MLflow
Model Serving
Online ML Worker
Governed Workflow
Stage 7M API / Workbench
Stage 7O AI Assistant
Airflow Scheduler
Airflow Webserver
Airflow Metadata Database
Operational Dashboard

```

**svg**

A validated runtime snapshot showed the Stage 7O assistant, Stage 7M API, Stage 7L workflow, online ML worker, model-serving service, MLflow, PostgreSQL, Kafka, Airflow, Spark and supporting services running together.

---

# 🛠️ Technology Stack

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#%EF%B8%8F-technology-stack)

| **DomainTechnologies**     |                                         |
| -------------------------- | --------------------------------------- |
| **Programming**            | Python, SQL                             |
| **Transactional Database** | PostgreSQL                              |
| **CDC**                    | Debezium                                |
| **Streaming**              | Apache Kafka                            |
| **Distributed Processing** | Apache Spark                            |
| **Cloud Warehouse**        | Google BigQuery                         |
| **Analytics Engineering**  | dbt                                     |
| **Orchestration**          | Apache Airflow                          |
| **Machine Learning**       | Python ML stack                         |
| **MLOps**                  | MLflow                                  |
| **API Layer**              | FastAPI                                 |
| **Governance**             | RBAC, API Keys, Human Approval Workflow |
| **AI Layer**               | Governed AI Assistant                   |
| **Business Intelligence**  | Power BI                                |
| **Containerization**       | Docker / Docker Compose                 |
| **Version Control**        | Git / GitHub                            |

---

# 📈 Engineering Highlights

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-engineering-highlights)

Some of the key implementation characteristics of the platform include:

- **26** historical snapshot tables
- **13** CDC topics
- **26** current-state analytical views
- **4** operational ML models
- **4** production-ready served models
- MLflow model registry with champion aliases
- CDC cutover-gap protection
- duplicate CDC-event validation
- Airflow orchestration and monitoring
- online ML inference
- governed operational decision workflow
- four-role RBAC model
- human approval boundaries
- provenance-aware AI assistance
- executive and AI-oriented Power BI reporting

---

# 🧩 End-to-End Operational Flow

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-end-to-end-operational-flow)

A simplified example of how a stockout signal moves through the platform:

```
1. Inventory transaction occurs in PostgreSQL
                     ↓
2. Debezium captures the database change
                     ↓
3. Kafka transports the CDC event
                     ↓
4. Spark processes historical/incremental state
                     ↓
5. BigQuery analytical state is updated
                     ↓
6. ML evaluates operational risk
                     ↓
7. Online ML emits a prediction
                     ↓
8. Governed workflow creates a decision case
                     ↓
9. Operator / Manager reviews the case
                     ↓
10. Governed action is approved or rejected
                     ↓
11. AI Assistant can investigate supporting evidence
                     ↓
12. Power BI exposes operational and executive outcomes

```

**svg**

This flow demonstrates the core principle of the platform:

> **Data → Intelligence → Governed Decision → Human-Controlled Action**

---

# 📁 Repository Structure

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-repository-structure)

The repository is organized by platform responsibility, with engineering, analytics, machine learning, orchestration, governance, and BI components separated into dedicated modules.

```
pharmstock-ai-platform-v2/
│
├── airflow/                  # Airflow runtime and orchestration support
├── dags/                     # Airflow DAG definitions
├── dbt/                      # Analytics engineering and warehouse transformations
├── docs/                     # Project documentation
│   └── assets/
│       └── screenshots/      # README platform screenshots
│
├── infra/                    # Docker and infrastructure configuration
├── ml/                       # ML training, registry and serving components
├── operations/               # Operational governance and AI layers
├── powerbi/                  # Power BI model / reporting assets
├── scripts/                  # Execution, validation and checkpoint scripts
├── spark/                    # Spark processing jobs
├── src/                      # Core PharmStock Python packages
├── tests/                    # Automated tests
└── warehouse/                # Warehouse-related assets and definitions

```

**svg**

> The exact repository structure evolves with the platform. Historical implementation notes and development artifacts are intentionally kept away from the primary repository landing experience.

# 🚀 Running the Platform

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-running-the-platform)

PharmStock V2 is a multi-service platform and requires several local and cloud dependencies.

## Prerequisites

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#prerequisites)

Typical prerequisites include:

- Git
- Docker Desktop / Docker Engine
- Docker Compose
- Python
- Google Cloud credentials for cloud-backed stages
- BigQuery project configuration
- Power BI Desktop for local BI development

Clone the repository:

```
git clone https://github.com/ayadigiliansDE/pharmstock-ai-platform.git
cd pharmstock-ai-platform
```

**svg**

The platform is implemented incrementally through validated stages and checkpoint scripts.

Before running cloud-backed components, configure the required environment variables and credentials for your environment.

> ⚠️ Do not commit API keys, Google Cloud credentials, service-account files, or other secrets to the repository.

---

# ✅ Validation Philosophy

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-validation-philosophy)

PharmStock V2 uses checkpoint-based validation rather than assuming that successful container startup means the complete platform is healthy.

Validation covers multiple layers, including:

- service health
- CDC connectivity
- historical rebuild integrity
- analytical state
- data-quality checks
- model availability
- model quality gates
- online worker heartbeat
- governed workflow health
- authentication
- RBAC
- AI governance boundaries

For example, the validated runtime reports Stage 7O as healthy with Stage 7M healthy underneath it, while Stage 7M reports Stage 7L healthy and procurement writes blocked.

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#for-example-the-validated-runtime-reports-stage-7o-as-healthy-with-stage-7m-healthy-underneath-it-while-stage-7m-reports-stage-7l-healthy-and-procurement-writes-blocked)

# 🛡️ Security & Responsible AI

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#%EF%B8%8F-security--responsible-ai)

This repository demonstrates architectural security and governance controls, but it should not be interpreted as a complete regulatory or production-security certification.

Implemented controls include:

- role-based authorization
- API-key protected operational endpoints
- deny-by-default action authorization
- human approval requirements
- blocked automatic procurement execution
- blocked direct database access from the AI assistant
- evidence provenance
- explicit synthetic-data disclosure

A real production deployment would additionally require organization-specific controls such as secret management, identity federation, network isolation, encryption policies, centralized audit infrastructure, regulatory review, disaster recovery, and formal security testing.

---

# ⚠️ Data & Deployment Disclaimer

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#%EF%B8%8F-data--deployment-disclaimer)

The project uses **synthetic/calibrated operational data** for engineering and production-style simulation.

It is designed as a **production-oriented / deployment-ready reference architecture**, but the repository should not be interpreted as evidence that the system is currently operating against live pharmacy production data.

Machine-learning predictions, replenishment recommendations, dashboards, and AI outputs in the repository are therefore demonstrations of the platform architecture and workflow.

---

# 🎯 Project Scope

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-project-scope)

PharmStock AI Platform V2 demonstrates an integrated implementation across:

**Data Engineering → Streaming → Cloud Analytics → Analytics Engineering → MLOps → Online ML → Decision Governance → Governed AI → Business Intelligence**

The objective is not simply to predict pharmacy demand.

The objective is to demonstrate how a prediction can travel through a controlled engineering system and become a **traceable, explainable, human-governed operational decision**.

---

## 📸 Platform Evidence

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-platform-evidence)

| **ComponentEvidence**   |                                   |
| ----------------------- | --------------------------------- |
| 🤖 Governed AI          | Stage 7O AI Assistant             |
| 🛡️ Decision Governance | Stage 7M Operational Workbench    |
| 🧪 MLOps                | MLflow Champion Model Registry    |
| 🔄 Orchestration        | Airflow Operational DAGs          |
| 📊 Executive Analytics  | Power BI Executive Operations     |
| 🧠 AI Operations        | Power BI AI & Decision Operations |

All screenshots shown above are captured from the implemented PharmStock V2 environment.

---

## 📌 Status

[svg](https://github.com/ayadigiliansDE/pharmstock-ai-platform/blob/main/README.md#-status)

**Current platform milestone: Stage 7O — Governed AI Assistant**

Core end-to-end capabilities implemented:

**CDC → Streaming → Distributed Processing → Cloud Analytics → ML → Online Inference → Governed Decisions → AI Assistance → BI**

---

**PharmStock AI Platform V2**
*From operational events to governed intelligence.*
