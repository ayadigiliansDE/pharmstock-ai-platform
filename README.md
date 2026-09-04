# 💊 PharmStock AI Platform V2

### Production-Oriented Pharmacy Data, Machine Learning & Governed AI Platform

> An end-to-end data engineering and AI platform that connects transactional pharmacy operations with CDC streaming, large-scale analytics, machine learning, governed operational decisions, AI-assisted investigation, and executive BI.

---

## 🚀 Project Overview

**PharmStock AI Platform V2** is an end-to-end pharmacy operations platform designed to demonstrate how modern data engineering, machine learning, analytics, and governed AI can work together as one integrated system.

The platform processes operational pharmacy data through a production-oriented architecture spanning:

**PostgreSQL → Debezium → Kafka → Apache Spark → BigQuery → dbt → Airflow → MLflow → Online ML → Governed Decision APIs → AI Assistant → Power BI**

It goes beyond a traditional analytics project by implementing:

- Change Data Capture (CDC) and event-driven data pipelines
- Large-scale historical rebuild and incremental processing
- Cloud analytical modeling with BigQuery and dbt
- Automated orchestration, monitoring, and data-quality checks
- Multi-model machine learning with MLflow lifecycle management
- Online ML inference
- Human-in-the-loop operational decision workflows
- Role-based access control and governed actions
- Grounded AI assistance with provenance and safety boundaries
- Executive and operational Power BI reporting

> **Data Transparency:** Operational data used in the platform is synthetic/calibrated and designed for production-style simulation. It must not be interpreted as live pharmacy operational data.

---

## 🏗️ Architecture at a Glance

```text
┌──────────────────────┐
│ Pharmacy Operations  │
│     PostgreSQL       │
└──────────┬───────────┘
           │
           │ CDC
           ▼
┌──────────────────────┐
│      Debezium        │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│        Kafka         │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│    Apache Spark      │
│ Snapshot + Streaming │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│      BigQuery        │
│ Raw / Current / Gold │
└──────────┬───────────┘
           │
     ┌─────┴─────┐
     ▼           ▼
┌─────────┐  ┌─────────┐
│   dbt   │  │ Airflow │
│ Models  │  │ DQ / Ops│
└────┬────┘  └────┬────┘
     │             │
     └──────┬──────┘
            ▼
┌──────────────────────┐
│ ML + MLflow Registry │
│ 4 Operational Models │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│   Online Inference   │
└──────────┬───────────┘
           ▼
┌────────────────────────────┐
│ Governed Decision Workflow │
│ Human Approval + RBAC      │
└──────────┬─────────────────┘
           │
      ┌────┴──────────┐
      ▼               ▼
┌──────────────┐ ┌──────────────┐
│ AI Assistant │ │   Power BI   │
│ Provenance & │ │ Executive &  │
│ Governance   │ │ Operational  │
└──────────────┘ └──────────────┘
```

---

## ✨ What Makes This Project Different

This repository is not a collection of isolated notebooks or disconnected demos.

It implements a connected platform where:

- operational transactions become CDC events,
- streaming and historical workloads converge into analytical models,
- machine-learning models are trained, versioned, promoted, and served,
- predictions become governed operational decision cases,
- sensitive actions remain human-controlled,
- the AI assistant queries governed evidence instead of bypassing operational boundaries,
- and Power BI exposes the final business and decision layer.

The architecture deliberately separates **prediction**, **recommendation**, **approval**, and **execution**.

Automatic supplier selection and automatic purchase-order creation are intentionally blocked within the governed workflow.

---

## 🧠 Governed AI Assistant

The Stage 7O assistant provides grounded operational investigation while preserving strict governance boundaries.

It exposes:

- governed operational evidence
- stockout-risk investigation
- evidence scope
- operational and reference provenance
- explicit synthetic-data disclosure
- blocked direct database access
- blocked assistant mutations
- blocked automatic supplier selection
- blocked automatic purchase-order creation

<p align="center">
  <img src="docs/assets/screenshots/stage7o-governed-ai-assistant.png"
       alt="PharmStock Stage 7O Governed AI Assistant"
       width="95%">
</p>

---

## 🛡️ Governed Operational Decision Workbench

The Stage 7M workbench converts ML signals into controlled operational decision cases.

The workbench implements:

- API-key authentication
- role-based access control
- viewer / operator / manager / admin roles
- governed case lifecycle
- acknowledgement and review
- draft approval / rejection
- controlled case closure
- human approval boundaries
- append-oriented operational auditing

<p align="center">
  <img src="docs/assets/screenshots/stage7m-governed-operational-decision-workbench.png"
       alt="PharmStock Stage 7M Governed Operational Decision Workbench"
       width="95%">
</p>
