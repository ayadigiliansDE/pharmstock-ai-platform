"""Stage 7O Assistant demand-serving orchestration.

Runs bounded incremental refreshes frequently and a wider reconciliation
daily. Database mutation is constrained behind the governed
assistant_api.refresh_branch_daily_demand() SECURITY DEFINER function.
"""

from __future__ import annotations

import subprocess
from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.operators.python import PythonOperator


CAIRO = pendulum.timezone("Africa/Cairo")


def run_incremental_refresh() -> None:
    subprocess.run(
        [
            "python",
            "/opt/pharmstock/scripts/run_stage7o_refresh.py",
            "--lookback-days",
            "2",
            "--airflow-task",
        ],
        cwd="/opt/pharmstock",
        check=True,
    )


def run_full_reconciliation() -> None:
    subprocess.run(
        [
            "python",
            "/opt/pharmstock/scripts/run_stage7o_refresh.py",
            "--full-reconciliation",
            "--airflow-task",
        ],
        cwd="/opt/pharmstock",
        check=True,
    )


DEFAULT_ARGS = {
    "owner": "pharmstock-platform",
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}


with DAG(
    dag_id="pharmstock_stage7o_demand_refresh",
    description="Incremental governed Assistant demand-serving refresh",
    start_date=pendulum.datetime(
        2026, 1, 1, tz=CAIRO
    ),
    schedule="*/15 * * * *",
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=[
        "pharmstock",
        "stage7o",
        "assistant",
        "serving",
    ],
) as incremental_dag:
    PythonOperator(
        task_id="refresh_recent_demand_serving",
        python_callable=run_incremental_refresh,
    )


with DAG(
    dag_id="pharmstock_stage7o_demand_reconciliation",
    description="Daily governed reconciliation of Assistant demand serving",
    start_date=pendulum.datetime(
        2026, 1, 1, tz=CAIRO
    ),
    schedule="15 2 * * *",
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=[
        "pharmstock",
        "stage7o",
        "assistant",
        "serving",
        "reconciliation",
    ],
) as reconciliation_dag:
    PythonOperator(
        task_id="reconcile_demand_serving",
        python_callable=run_full_reconciliation,
    )
