# Stage 7J — Airflow + Data Quality + Monitoring

Stage 7J adds a local Airflow control plane and a storage-safe quality gate over the completed Stage 7H/7I warehouse.

## Principles

- BigQuery is read-only in this stage: no raw copies, no DML, no streaming, no materialized monitoring tables.
- Capacity is a first-class quality gate: PASS below 8.2 GiB, WARN from 8.2 GiB, FAIL at 8.5 GiB or above.
- The Airflow DAG runs every 15 minutes and uses the same Python quality contract as manual acceptance.
- Monitoring evidence is local under `artifacts/stage7j`.

## Checks

1. 26 raw BigQuery tables.
2. 31,954,735 raw baseline rows.
3. 26 current-state views.
4. 3 dbt Gold tables.
5. Zero duplicate CDC event rows.
6. CDC event store is readable and contains verified events.
7. Debezium connector and tasks are RUNNING.
8. BigQuery storage remains below the warning threshold.

## Monitoring outputs

- `artifacts/stage7j/dq_report.json`
- `artifacts/stage7j/health_history.jsonl`
- `artifacts/stage7j/monitoring_dashboard.html`
- `artifacts/stage7j/_SUCCESS`

Airflow UI: `http://localhost:8088` (admin/admin for local development only).
