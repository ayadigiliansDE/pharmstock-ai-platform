# PharmStock AI Platform

> End-to-end pharmacy data, streaming, analytics, machine learning, governed decision-support, and AI-assistant platform.

PharmStock AI Platform is a production-style reference architecture for building a modern pharmacy data platform across transactional systems, event streaming, analytical processing, machine learning, operational decision workflows, business intelligence, and governed AI assistance.

The platform is implemented incrementally and tested stage by stage, with explicit boundaries between operational data, analytical workloads, ML inference, human approval, and AI-assisted explanation.

---

## Overview

The platform demonstrates an end-to-end architecture covering:

- pharmaceutical product and pharmacy domain modeling
- configurable synthetic pharmacy-network simulation
- inventory, FEFO, demand, sales, procurement, and supplier workflows
- Apache Kafka event streaming
- durable event processing and dead-letter handling
- Debezium CDC
- Apache Spark Structured Streaming
- Bronze and Silver analytical processing
- BigQuery warehouse contracts and cloud deployment workflows
- dbt staging, dimensions, facts, marts, and data-quality tests
- Airflow orchestration and monitoring
- ML training, evaluation, MLflow tracking, and serving
- online streaming ML decisions
- governed human approval workflows
- operational decision APIs
- Power BI semantic-serving contracts
- governed read-only AI assistance

---

## Architecture

```text
Pharmaceutical Reference Data
            |
            v
Canonical Product Master
            |
            +---------------------------+
            |                           |
            v                           v
Synthetic Pharmacy Network       Operational PostgreSQL
Branches / POS / Inventory              |
Suppliers / Procurement                 v
                                   Debezium CDC
                                        |
                                        v
                                   Apache Kafka
                                    /        \
                                   v          v
                         Spark Streaming    Online ML
                         Bronze / Silver    Stage 7K5
                              |               |
                              v               v
                           BigQuery      Governed Decision
                              |          Workflow - Stage 7L
                              v               |
                             dbt              v
                           /    \        Operational API
                          v      v        Stage 7M
                      Power BI  ML            |
                      Stage 7N  MLflow        v
                                       Governed AI
                                       Assistant - 7O

