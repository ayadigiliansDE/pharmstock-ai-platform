"""Stage 7O governed demand-serving refresh runner."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ARTIFACT_ROOT = Path("artifacts/stage7o")
REPORT_PATH = ARTIFACT_ROOT / "demand_refresh_report.json"
SUCCESS_PATH = ARTIFACT_ROOT / "_REFRESH_SUCCESS"

DEFAULT_INCREMENTAL_LOOKBACK_DAYS = 2
DEFAULT_RECONCILIATION_LOOKBACK_DAYS = 35


def _import_psycopg2():
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError as exc:
        raise RuntimeError("psycopg2 is required for Stage 7O refresh") from exc
    return psycopg2, RealDictCursor


def _connect():
    psycopg2, real_dict_cursor = _import_psycopg2()

    conn = psycopg2.connect(
        host=os.getenv(
            "PHARMSTOCK_ASSISTANT_REFRESH_HOST",
            "postgres",
        ),
        port=int(
            os.getenv(
                "PHARMSTOCK_ASSISTANT_REFRESH_PORT",
                "5432",
            )
        ),
        dbname=os.getenv(
            "PHARMSTOCK_ASSISTANT_REFRESH_DB",
            "pharmstock_ops",
        ),
        user=os.getenv(
            "PHARMSTOCK_ASSISTANT_REFRESH_USER",
            "pharmstock_assistant_refresh",
        ),
        password=os.getenv(
            "PHARMSTOCK_ASSISTANT_REFRESH_PASSWORD",
            "",
        ),
        application_name="pharmstock-stage7o-refresh",
        connect_timeout=8,
        options=(
            "-c statement_timeout=120000 "
            "-c lock_timeout=30000 "
            "-c idle_in_transaction_session_timeout=30000"
        ),
        cursor_factory=real_dict_cursor,
    )

    return conn


def _require_password() -> None:
    if not os.getenv("PHARMSTOCK_ASSISTANT_REFRESH_PASSWORD", "").strip():
        raise RuntimeError(
            "PHARMSTOCK_ASSISTANT_REFRESH_PASSWORD is required"
        )


def _security_check(cursor) -> dict[str, bool]:
    cursor.execute(
        """
        SELECT
            has_function_privilege(
                current_user,
                'assistant_api.refresh_branch_daily_demand(integer)',
                'EXECUTE'
            ) AS can_execute_refresh,

            has_table_privilege(
                current_user,
                'assistant_api.v_branch_daily_demand',
                'SELECT'
            ) AS can_read_daily_view,

            has_table_privilege(
                current_user,
                'assistant_api.branch_daily_demand',
                'INSERT'
            ) AS can_direct_insert_serving,

            has_table_privilege(
                current_user,
                'assistant_api.branch_daily_demand',
                'UPDATE'
            ) AS can_direct_update_serving,

            has_table_privilege(
                current_user,
                'assistant_api.branch_daily_demand',
                'DELETE'
            ) AS can_direct_delete_serving,

            has_schema_privilege(
                current_user,
                'procurement',
                'USAGE'
            ) AS can_use_procurement_schema
        """
    )

    row = cursor.fetchone()
    return {key: bool(value) for key, value in row.items()}


def _validate_security(result: dict[str, bool]) -> None:
    expected = {
        "can_execute_refresh": True,
        "can_read_daily_view": True,
        "can_direct_insert_serving": False,
        "can_direct_update_serving": False,
        "can_direct_delete_serving": False,
        "can_use_procurement_schema": False,
    }

    if result != expected:
        raise RuntimeError(
            "Stage 7O refresh-role security contract failed: "
            f"observed={result}; expected={expected}"
        )


def _run_refresh(cursor, lookback_days: int) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT assistant_api.refresh_branch_daily_demand(%s)
            AS refresh_result
        """,
        (lookback_days,),
    )

    row = cursor.fetchone()
    result = row["refresh_result"]

    if isinstance(result, str):
        result = json.loads(result)

    if not isinstance(result, dict):
        raise RuntimeError(
            f"unexpected Stage 7O refresh result: {result!r}"
        )

    if result.get("status") not in {"PASS", "NO_SOURCE_DATA"}:
        raise RuntimeError(
            f"Stage 7O refresh failed: {result}"
        )

    return result


def _analytical_state(cursor) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT
            provenance_class,
            analytical_as_of_date
        FROM assistant_api.v_demand_analytical_as_of
        ORDER BY provenance_class
        """
    )

    rows = cursor.fetchall()

    return [
        {
            "provenance_class": row["provenance_class"],
            "analytical_as_of_date": (
                row["analytical_as_of_date"].isoformat()
                if row["analytical_as_of_date"] is not None
                else None
            ),
        }
        for row in rows
    ]


def run_refresh(lookback_days: int) -> dict[str, Any]:
    _require_password()

    conn = _connect()

    try:
        with conn:
            with conn.cursor() as cursor:
                security = _security_check(cursor)
                _validate_security(security)

                refresh_result = _run_refresh(
                    cursor,
                    lookback_days,
                )

                analytical_state = _analytical_state(cursor)

        return {
            "stage": "7O",
            "component": "DEMAND_SERVING_REFRESH",
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "PASS",
            "lookback_days": lookback_days,
            "refresh": refresh_result,
            "analytical_state": analytical_state,
            "security": security,
            "direct_database_mutation_by_assistant": False,
            "automatic_purchase_order_creation": False,
            "automatic_supplier_selection": False,
        }

    finally:
        conn.close()


def _persist(report: dict[str, Any]) -> None:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)

    REPORT_PATH.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    SUCCESS_PATH.write_text(
        report["generated_at"] + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh Stage 7O Assistant demand serving data"
    )

    parser.add_argument(
        "--lookback-days",
        type=int,
        default=DEFAULT_INCREMENTAL_LOOKBACK_DAYS,
    )

    parser.add_argument(
        "--full-reconciliation",
        action="store_true",
        help="recompute the wider reconciliation window",
    )

    parser.add_argument(
        "--airflow-task",
        action="store_true",
        help="run as an Airflow scheduled task",
    )

    args = parser.parse_args()

    lookback_days = (
        DEFAULT_RECONCILIATION_LOOKBACK_DAYS
        if args.full_reconciliation
        else args.lookback_days
    )

    if not 1 <= lookback_days <= 90:
        raise SystemExit("lookback days must be between 1 and 90")

    print("=== PharmStock V2 / Stage 7O Demand Refresh ===")
    print(f"Refresh lookback:       {lookback_days} day(s)")
    print("Business timezone:      Africa/Cairo")
    print("Execution principal:    pharmstock_assistant_refresh")
    print("Direct serving writes:  BLOCKED")
    print("Procurement access:     BLOCKED")

    report = run_refresh(lookback_days)
    _persist(report)

    refresh = report["refresh"]

    print(f"Refresh status:         {refresh.get('status')}")
    print(f"Data as-of:             {refresh.get('data_as_of')}")
    print(f"Window start:           {refresh.get('window_start')}")
    print(f"Window end:             {refresh.get('window_end')}")
    print(f"Source events:          {refresh.get('source_events')}")
    print(
        "Aggregate rows:        "
        f"{refresh.get('aggregate_rows_written')}"
    )

    for state in report["analytical_state"]:
        print(
            "Analytical as-of:      "
            f"{state['provenance_class']}="
            f"{state['analytical_as_of_date']}"
        )

    if args.airflow_task:
        print("STAGE_7O_AIRFLOW_REFRESH_STATUS=PASS")
    elif args.full_reconciliation:
        print("STAGE_7O_RECONCILIATION_STATUS=PASS")
    else:
        print("STAGE_7O_REFRESH_STATUS=PASS")


if __name__ == "__main__":
    main()
