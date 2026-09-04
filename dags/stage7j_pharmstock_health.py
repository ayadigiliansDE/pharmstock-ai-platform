"""Production-style Stage 7J health DAG.

The DAG is intentionally read-only against BigQuery. It runs the same checked
monitoring contract used by the host acceptance script, preventing drift
between scheduled and manual quality gates.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta

from airflow.operators.python import PythonOperator

from airflow import DAG


def run_stage7j_quality_gate() -> None:
    subprocess.run(
        ["python", "/opt/pharmstock/scripts/run_stage7j.py", "--airflow-task"],
        cwd="/opt/pharmstock",
        check=True,
    )


with DAG(
    dag_id="pharmstock_stage7j_health",
    description="PharmStock BigQuery DQ, CDC health and storage guard",
    start_date=datetime(2026, 1, 1),
    schedule="*/15 * * * *",
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "pharmstock-platform",
        "retries": 1,
        "retry_delay": timedelta(minutes=2),
    },
    tags=["pharmstock", "dq", "monitoring", "stage7j"],
) as dag:
    PythonOperator(
        task_id="quality_and_capacity_gate",
        python_callable=run_stage7j_quality_gate,
    )
