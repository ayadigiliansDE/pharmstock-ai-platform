"""Stage 7M FastAPI service for governed operational decision cases."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from pharmstock.onprem.stage7l import next_status
from pharmstock.onprem.stage7m import (
    ACTIONS,
    STAGE7M_VERSION,
    Principal,
    action_allowed,
    authenticate_api_key,
    stage7m_contract,
)

ARTIFACT_ROOT = Path(os.getenv("PHARMSTOCK_STAGE7M_ARTIFACT_ROOT", "artifacts/stage7m"))
STAGE7L_HEARTBEAT = Path("artifacts/stage7l/worker_heartbeat.json")
WORKBENCH_PATH = Path("operations/stage7m/workbench.html")


class ActionRequest(BaseModel):
    action: str = Field(min_length=1, max_length=40)
    note: str = Field(default="", max_length=1000)


class ApiRuntimeError(RuntimeError):
    """Raised for Stage 7M runtime contract failures."""


def _import_psycopg():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover - container dependency boundary
        raise ApiRuntimeError("psycopg is required by Stage 7M") from exc
    return psycopg, dict_row


@contextmanager
def _connect():
    psycopg, dict_row = _import_psycopg()
    conn = psycopg.connect(
        host=os.getenv("PHARMSTOCK_STAGE7M_POSTGRES_HOST", "postgres"),
        port=int(os.getenv("PHARMSTOCK_STAGE7M_POSTGRES_PORT", "5432")),
        dbname=os.getenv("PHARMSTOCK_STAGE7M_POSTGRES_DB", "pharmstock_ops"),
        user=os.getenv("PHARMSTOCK_STAGE7M_POSTGRES_USER", "pharmstock_workbench"),
        password=os.getenv(
            "PHARMSTOCK_STAGE7M_POSTGRES_PASSWORD",
            "pharmstock_local_dev_workbench",
        ),
        row_factory=dict_row,
        connect_timeout=8,
    )
    try:
        yield conn
    finally:
        conn.close()


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime,)):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


def _json_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_value(value) for key, value in row.items()}


def _principal(
    x_pharmstock_api_key: str | None = Header(default=None, alias="X-PharmStock-Api-Key"),
) -> Principal:
    principal = authenticate_api_key(x_pharmstock_api_key or "")
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="valid X-PharmStock-Api-Key is required",
        )
    return principal


PRINCIPAL_DEPENDENCY = Depends(_principal)


def _require_action(principal: Principal, action: str) -> None:
    if action not in ACTIONS or not action_allowed(principal.role, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"role {principal.role!r} cannot perform action {action!r}",
        )


def _catalog_oid(conn, schema_name: str, relation_name: str) -> int:
    row = conn.execute(
        """
        SELECT c.oid::bigint AS oid
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relname = %s
        """,
        (schema_name, relation_name),
    ).fetchone()
    if row is None:
        raise ApiRuntimeError(f"missing relation: {schema_name}.{relation_name}")
    return int(row["oid"])


def _role_safety(conn) -> dict[str, bool]:
    schema_row = conn.execute(
        "SELECT oid::bigint AS oid FROM pg_catalog.pg_namespace WHERE nspname = 'procurement'"
    ).fetchone()
    if schema_row is None:
        raise ApiRuntimeError("procurement schema is missing")
    schema_oid = int(schema_row["oid"])
    po_oid = _catalog_oid(conn, "procurement", "purchase_order")
    goods_receipt_oid = _catalog_oid(conn, "procurement", "goods_receipt")
    row = conn.execute(
        """
        SELECT
            has_schema_privilege(current_user, %s::oid, 'USAGE') AS procurement_usage,
            has_table_privilege(current_user, %s::oid, 'INSERT') AS po_insert,
            has_table_privilege(current_user, %s::oid, 'UPDATE') AS po_update,
            has_table_privilege(current_user, %s::oid, 'DELETE') AS po_delete,
            has_table_privilege(current_user, %s::oid, 'INSERT') AS receipt_insert
        """,
        (schema_oid, po_oid, po_oid, po_oid, goods_receipt_oid),
    ).fetchone()
    return {key: bool(value) for key, value in dict(row).items()}


def _stage7l_freshness() -> dict[str, Any]:
    if not STAGE7L_HEARTBEAT.is_file():
        return {"healthy": False, "reason": "heartbeat_missing"}
    try:
        heartbeat = json.loads(STAGE7L_HEARTBEAT.read_text(encoding="utf-8"))
        generated = datetime.fromisoformat(str(heartbeat["generated_at"]))
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return {"healthy": False, "reason": "heartbeat_invalid"}
    age = max(0.0, (datetime.now(UTC) - generated).total_seconds())
    max_age = int(os.getenv("PHARMSTOCK_STAGE7M_STAGE7L_MAX_AGE_SECONDS", "90"))
    return {
        "healthy": heartbeat.get("status") == "HEALTHY" and age <= max_age,
        "status": heartbeat.get("status"),
        "age_seconds": round(age, 3),
        "max_age_seconds": max_age,
    }


def _summary(conn) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE status IN ('OPEN', 'ACKNOWLEDGED', 'APPROVED_DRAFT'))
                ::integer AS active_cases,
            COUNT(*) FILTER (WHERE status = 'OPEN')::integer AS open_cases,
            COUNT(*) FILTER (WHERE status = 'ACKNOWLEDGED')::integer AS acknowledged_cases,
            COUNT(*) FILTER (WHERE status = 'APPROVED_DRAFT')::integer AS approved_drafts,
            COUNT(*) FILTER (WHERE status = 'REJECTED')::integer AS rejected_cases,
            COUNT(*) FILTER (WHERE status = 'CLOSED')::integer AS closed_cases,
            COUNT(*) FILTER (WHERE severity IN ('HIGH', 'CRITICAL')
                AND status IN ('OPEN', 'ACKNOWLEDGED'))::integer AS high_priority_cases
        FROM decision_ops.decision_case
        """
    ).fetchone()
    return {key: int(value) for key, value in dict(row).items()}


def _list_cases(
    conn,
    *,
    case_status: str | None,
    decision_type: str | None,
    severity: str | None,
    branch_id: UUID | None,
    limit: int,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if case_status:
        clauses.append("status = %s")
        params.append(case_status.upper())
    if decision_type:
        clauses.append("decision_type = %s")
        params.append(decision_type.upper())
    if severity:
        clauses.append("severity = %s")
        params.append(severity.upper())
    if branch_id:
        clauses.append("branch_id = %s::uuid")
        params.append(str(branch_id))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, min(limit, 500)))
    rows = conn.execute(
        f"""
        SELECT *
        FROM decision_ops.v_case_workbench
        {where}
        ORDER BY
            CASE severity
                WHEN 'CRITICAL' THEN 5
                WHEN 'HIGH' THEN 4
                WHEN 'MEDIUM' THEN 3
                WHEN 'WATCH' THEN 2
                ELSE 1
            END DESC,
            updated_at DESC
        LIMIT %s
        """,
        params,
    ).fetchall()
    return [_json_row(dict(row)) for row in rows]


def _inventory_context(
    conn,
    *,
    branch_id: UUID | None,
    product_id: UUID | None,
    below_reorder: bool | None,
    zero_stock: bool | None,
    limit: int,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if branch_id is not None:
        clauses.append("branch_id = %s::uuid")
        params.append(str(branch_id))

    if product_id is not None:
        clauses.append("product_id = %s::uuid")
        params.append(str(product_id))

    if below_reorder is not None:
        clauses.append("below_reorder = %s")
        params.append(below_reorder)

    if zero_stock is not None:
        clauses.append("zero_stock = %s")
        params.append(zero_stock)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    params.append(max(1, min(limit, 500)))

    rows = conn.execute(
        f"""
        SELECT
            branch_id,
            branch_code,
            branch_name,
            governorate,
            representative_city,
            product_id,
            trade_name_en,
            trade_name_ar,
            scientific_name,
            manufacturer,
            on_hand_units,
            reserved_units,
            available_units,
            reorder_point_units,
            target_stock_units,
            zero_stock,
            below_reorder,
            last_movement_at,
            inventory_version,
            updated_at,
            operational_provenance_class,
            reference_provenance_class
        FROM assistant_api.v_inventory_context
        {where}
        ORDER BY
            zero_stock DESC,
            below_reorder DESC,
            available_units ASC,
            updated_at DESC
        LIMIT %s
        """,
        params,
    ).fetchall()

    return [_json_row(dict(row)) for row in rows]


def _ml_signals(
    conn,
    *,
    branch_id: UUID | None,
    product_id: UUID | None,
    model_key: str | None,
    severity: str | None,
    action_required: bool | None,
    limit: int,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if branch_id is not None:
        clauses.append("branch_id = %s::uuid")
        params.append(str(branch_id))

    if product_id is not None:
        clauses.append("product_id = %s::uuid")
        params.append(str(product_id))

    if model_key:
        clauses.append("model_key = %s")
        params.append(model_key.strip())

    if severity:
        clauses.append("severity = %s")
        params.append(severity.strip().upper())

    if action_required is not None:
        clauses.append("action_required = %s")
        params.append(action_required)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    params.append(max(1, min(limit, 500)))

    rows = conn.execute(
        f"""
        SELECT
            branch_id,
            branch_code,
            branch_name,
            governorate,
            representative_city,
            product_id,
            trade_name_en,
            trade_name_ar,
            scientific_name,
            manufacturer,
            model_key,
            model_version,
            feature_as_of_date,
            prediction_value,
            probability,
            threshold,
            action_required,
            severity,
            updated_at,
            operational_provenance_class,
            reference_provenance_class
        FROM assistant_api.v_ml_signal
        {where}
        ORDER BY
            action_required DESC,
            CASE severity
                WHEN 'CRITICAL' THEN 5
                WHEN 'HIGH' THEN 4
                WHEN 'MEDIUM' THEN 3
                WHEN 'WATCH' THEN 2
                ELSE 1
            END DESC,
            probability DESC NULLS LAST,
            prediction_value DESC NULLS LAST,
            updated_at DESC
        LIMIT %s
        """,
        params,
    ).fetchall()

    return [_json_row(dict(row)) for row in rows]



def _demand_context(
    conn,
    *,
    branch_id: UUID | None,
    provenance_class: str | None,
    days: int,
) -> dict[str, Any]:
    days = max(1, min(days, 35))

    provenance_clause = ""
    provenance_params: list[Any] = []

    if provenance_class:
        provenance_clause = "WHERE provenance_class = %s"
        provenance_params.append(provenance_class.strip())

    analytical_rows = conn.execute(
        f"""
        SELECT
            provenance_class,
            analytical_as_of_date
        FROM assistant_api.v_demand_analytical_as_of
        {provenance_clause}
        ORDER BY provenance_class
        """,
        provenance_params,
    ).fetchall()

    analytical_state = [
        _json_row(dict(row))
        for row in analytical_rows
    ]

    operational_params: list[Any] = []
    operational_where = ""

    if provenance_class:
        operational_where = "WHERE provenance_class = %s"
        operational_params.append(provenance_class.strip())

    operational_row = conn.execute(
        f"""
        SELECT MAX(business_date) AS operational_data_as_of
        FROM assistant_api.v_branch_daily_demand
        {operational_where}
        """,
        operational_params,
    ).fetchone()

    operational_data_as_of = (
        _json_row(dict(operational_row)).get("operational_data_as_of")
        if operational_row
        else None
    )

    filters: list[str] = []
    params: list[Any] = []

    if provenance_class:
        filters.append("d.provenance_class = %s")
        params.append(provenance_class.strip())

    if branch_id is not None:
        filters.append("d.branch_id = %s::uuid")
        params.append(str(branch_id))

    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    params.append(days)

    if branch_id is None:
        rows = conn.execute(
            f"""
            WITH analytical AS (
                SELECT
                    provenance_class,
                    analytical_as_of_date
                FROM assistant_api.v_demand_analytical_as_of
            )
            SELECT
                d.business_date,
                d.provenance_class,
                a.analytical_as_of_date,
                COUNT(DISTINCT d.branch_id)::integer AS active_branches,
                SUM(d.demand_attempts)::bigint AS demand_attempts,
                SUM(d.requested_units)::bigint AS requested_units,
                SUM(d.fulfilled_units)::bigint AS fulfilled_units,
                SUM(d.lost_units)::bigint AS lost_units,
                SUM(d.stockout_attempts)::bigint AS stockout_attempts,
                CASE
                    WHEN SUM(d.requested_units) > 0
                    THEN ROUND(
                        SUM(d.fulfilled_units)::numeric
                        / SUM(d.requested_units)::numeric,
                        6
                    )
                    ELSE NULL
                END AS fill_rate
            FROM assistant_api.v_branch_daily_demand d
            JOIN analytical a
              ON a.provenance_class = d.provenance_class
            {where}
              {"AND" if where else "WHERE"}
              d.business_date BETWEEN
                  a.analytical_as_of_date
                  - ((%s::integer - 1) * INTERVAL '1 day')
                  AND a.analytical_as_of_date
            GROUP BY
                d.business_date,
                d.provenance_class,
                a.analytical_as_of_date
            ORDER BY
                d.provenance_class,
                d.business_date
            """,
            params,
        ).fetchall()
    else:
        rows = conn.execute(
            f"""
            WITH analytical AS (
                SELECT
                    provenance_class,
                    analytical_as_of_date
                FROM assistant_api.v_demand_analytical_as_of
            )
            SELECT
                d.business_date,
                d.branch_id,
                d.branch_code,
                d.branch_name,
                d.governorate,
                d.representative_city,
                d.provenance_class,
                a.analytical_as_of_date,
                d.demand_attempts,
                d.requested_units,
                d.fulfilled_units,
                d.lost_units,
                d.stockout_attempts,
                d.fill_rate,
                d.first_transaction_at,
                d.last_transaction_at,
                d.refreshed_at
            FROM assistant_api.v_branch_daily_demand d
            JOIN analytical a
              ON a.provenance_class = d.provenance_class
            {where}
              {"AND" if where else "WHERE"}
              d.business_date BETWEEN
                  a.analytical_as_of_date
                  - ((%s::integer - 1) * INTERVAL '1 day')
                  AND a.analytical_as_of_date
            ORDER BY
                d.provenance_class,
                d.business_date
            """,
            params,
        ).fetchall()

    return {
        "operational_data_as_of": operational_data_as_of,
        "analytical_state": analytical_state,
        "days": days,
        "scope": "BRANCH" if branch_id is not None else "NETWORK",
        "items": [_json_row(dict(row)) for row in rows],
    }


def _supplier_context(
    conn,
    *,
    is_active: bool | None,
    supplier_type: str | None,
    service_scope: str | None,
    metric: str,
    limit: int,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if is_active is not None:
        clauses.append("is_active = %s")
        params.append(is_active)

    if supplier_type:
        clauses.append("supplier_type = %s")
        params.append(supplier_type.strip())

    if service_scope:
        clauses.append("service_scope = %s")
        params.append(service_scope.strip())

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    metric_key = metric.strip().lower()

    order_by = {
        "lead_time": """
            avg_actual_lead_time_days DESC NULLS LAST,
            delayed_receipt_rate DESC NULLS LAST,
            supplier_code
        """,
        "delay_rate": """
            delayed_receipt_rate DESC NULLS LAST,
            avg_actual_lead_time_days DESC NULLS LAST,
            supplier_code
        """,
        "reliability": """
            reliability_score ASC NULLS LAST,
            avg_actual_lead_time_days DESC NULLS LAST,
            supplier_code
        """,
    }.get(metric_key)

    if order_by is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "metric must be one of: "
                "lead_time, delay_rate, reliability"
            ),
        )

    params.append(max(1, min(limit, 500)))

    rows = conn.execute(
        f"""
        SELECT
            supplier_id,
            supplier_code,
            supplier_name,
            supplier_type,
            service_scope,
            reliability_score,
            nominal_lead_time_days,
            is_active,
            purchase_order_count,
            received_po_count,
            open_po_count,
            ordered_cost_egp,
            receipt_count,
            avg_actual_lead_time_days,
            delayed_receipt_count,
            delayed_receipt_rate,
            received_cost_egp,
            latest_ordered_at,
            latest_received_at,
            operational_provenance_class,
            reference_provenance_class
        FROM assistant_api.v_supplier_context
        {where}
        ORDER BY {order_by}
        LIMIT %s
        """,
        params,
    ).fetchall()

    return [_json_row(dict(row)) for row in rows]



def _case_detail(conn, case_id: str) -> dict[str, Any] | None:
    case = conn.execute(
        "SELECT * FROM decision_ops.v_case_workbench WHERE case_id = %s::uuid",
        (case_id,),
    ).fetchone()
    if case is None:
        return None
    evidence = conn.execute(
        """
        SELECT prediction_event_id, model_key, model_version, severity, action_required,
               recommended_units, probability, threshold, observed_at
        FROM decision_ops.decision_evidence
        WHERE case_id = %s::uuid
        ORDER BY observed_at DESC, prediction_event_id DESC
        LIMIT 50
        """,
        (case_id,),
    ).fetchall()
    audit = conn.execute(
        """
        SELECT audit_id, action, from_status, to_status, actor_type, actor_id, note, created_at
        FROM decision_ops.decision_audit
        WHERE case_id = %s::uuid
        ORDER BY created_at DESC, audit_id DESC
        LIMIT 100
        """,
        (case_id,),
    ).fetchall()
    result = _json_row(dict(case))
    result["evidence"] = [_json_row(dict(row)) for row in evidence]
    result["audit"] = [_json_row(dict(row)) for row in audit]
    return result


def _transition_case(conn, case_id: str, action: str, principal: Principal, note: str) -> str:
    row = conn.execute(
        """
        SELECT case_id, decision_type, status
        FROM decision_ops.decision_case
        WHERE case_id = %s::uuid
        FOR UPDATE
        """,
        (case_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="decision case not found")
    current = str(row["status"])
    decision_type = str(row["decision_type"])
    try:
        target = next_status(current, action, decision_type)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    timestamp_column = {
        "ACKNOWLEDGED": "acknowledged_at",
        "APPROVED_DRAFT": "decided_at",
        "REJECTED": "decided_at",
        "CLOSED": "closed_at",
    }[target]
    resolution = {
        "APPROVED_DRAFT": "HUMAN_APPROVED_DRAFT",
        "REJECTED": "HUMAN_REJECTED",
        "CLOSED": "HUMAN_CLOSED",
    }.get(target)
    conn.execute(
        f"""
        UPDATE decision_ops.decision_case
        SET status = %s, {timestamp_column} = now(),
            resolution_code = COALESCE(%s, resolution_code), updated_at = now()
        WHERE case_id = %s::uuid
        """,
        (target, resolution, case_id),
    )
    if decision_type == "REORDER":
        draft_status = {
            "APPROVED_DRAFT": "APPROVED",
            "REJECTED": "REJECTED",
            "CLOSED": "CLOSED",
        }.get(target)
        if draft_status == "APPROVED":
            conn.execute(
                """
                UPDATE decision_ops.replenishment_draft
                SET draft_status = 'APPROVED', approved_by = %s,
                    approved_at = now(), updated_at = now()
                WHERE case_id = %s::uuid
                """,
                (principal.actor_id, case_id),
            )
        elif draft_status:
            conn.execute(
                """
                UPDATE decision_ops.replenishment_draft
                SET draft_status = %s, updated_at = now()
                WHERE case_id = %s::uuid
                """,
                (draft_status, case_id),
            )
    conn.execute(
        """
        INSERT INTO decision_ops.decision_audit (
            case_id, action, from_status, to_status, actor_type, actor_id, note
        ) VALUES (%s::uuid, %s, %s, %s, 'HUMAN', %s, %s)
        """,
        (
            case_id,
            action.upper().replace("-", "_"),
            current,
            target,
            principal.actor_id,
            note or None,
        ),
    )
    return target


app = FastAPI(
    title="PharmStock Operational Decision API",
    version=STAGE7M_VERSION,
    docs_url="/docs",
    redoc_url=None,
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or str(uuid4())
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
def health() -> dict[str, Any]:
    upstream = _stage7l_freshness()
    with _connect() as conn:
        conn.execute("SELECT 1")
        safety = _role_safety(conn)
        summary = _summary(conn)
        conn.rollback()
    unsafe = any(safety.values())
    healthy = bool(upstream.get("healthy")) and not unsafe
    if not healthy:
        raise HTTPException(
            status_code=503,
            detail={"upstream": upstream, "role_safety": safety},
        )
    return {
        "status": "HEALTHY",
        "stage": "7M",
        "version": STAGE7M_VERSION,
        "stage7l": upstream,
        "procurement_write_blocked": True,
        "automatic_po_creation": False,
        "metrics": summary,
    }


@app.get("/v1/meta")
def meta(_: Principal = PRINCIPAL_DEPENDENCY) -> dict[str, object]:
    return stage7m_contract()


@app.get("/v1/metrics/summary")
def metrics_summary(_: Principal = PRINCIPAL_DEPENDENCY) -> dict[str, int]:
    with _connect() as conn:
        result = _summary(conn)
        conn.rollback()
    return result


@app.get("/v1/assistant/inventory")
def assistant_inventory(
    branch_id: UUID | None = None,
    product_id: UUID | None = None,
    below_reorder: bool | None = None,
    zero_stock: bool | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    _: Principal = PRINCIPAL_DEPENDENCY,
) -> dict[str, Any]:
    with _connect() as conn:
        items = _inventory_context(
            conn,
            branch_id=branch_id,
            product_id=product_id,
            below_reorder=below_reorder,
            zero_stock=zero_stock,
            limit=limit,
        )
        conn.rollback()

    return {
        "count": len(items),
        "items": items,
        "read_only": True,
    }


@app.get("/v1/assistant/ml-signals")
def assistant_ml_signals(
    branch_id: UUID | None = None,
    product_id: UUID | None = None,
    model_key: str | None = None,
    severity: str | None = None,
    action_required: bool | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    _: Principal = PRINCIPAL_DEPENDENCY,
) -> dict[str, Any]:
    with _connect() as conn:
        items = _ml_signals(
            conn,
            branch_id=branch_id,
            product_id=product_id,
            model_key=model_key,
            severity=severity,
            action_required=action_required,
            limit=limit,
        )
        conn.rollback()

    return {
        "count": len(items),
        "items": items,
        "read_only": True,
    }



@app.get("/v1/assistant/demand")
def assistant_demand(
    branch_id: UUID | None = None,
    provenance_class: str | None = None,
    days: int = Query(default=14, ge=1, le=35),
    _: Principal = PRINCIPAL_DEPENDENCY,
) -> dict[str, Any]:
    with _connect() as conn:
        result = _demand_context(
            conn,
            branch_id=branch_id,
            provenance_class=provenance_class,
            days=days,
        )
        conn.rollback()

    return {
        **result,
        "read_only": True,
    }


@app.get("/v1/assistant/suppliers")
def assistant_suppliers(
    is_active: bool | None = None,
    supplier_type: str | None = None,
    service_scope: str | None = None,
    metric: str = Query(default="lead_time"),
    limit: int = Query(default=100, ge=1, le=500),
    _: Principal = PRINCIPAL_DEPENDENCY,
) -> dict[str, Any]:
    with _connect() as conn:
        items = _supplier_context(
            conn,
            is_active=is_active,
            supplier_type=supplier_type,
            service_scope=service_scope,
            metric=metric,
            limit=limit,
        )
        conn.rollback()

    return {
        "metric": metric.strip().lower(),
        "count": len(items),
        "items": items,
        "read_only": True,
        "automatic_supplier_selection": False,
        "automatic_purchase_order_creation": False,
    }



@app.get("/v1/cases")
def cases(
    case_status: str | None = Query(default=None, alias="status"),
    decision_type: str | None = None,
    severity: str | None = None,
    branch_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    _: Principal = PRINCIPAL_DEPENDENCY,
) -> dict[str, Any]:
    with _connect() as conn:
        items = _list_cases(
            conn,
            case_status=case_status,
            decision_type=decision_type,
            severity=severity,
            branch_id=branch_id,
            limit=limit,
        )
        conn.rollback()
    return {"count": len(items), "items": items}


@app.get("/v1/cases/{case_id}")
def case_detail(case_id: UUID, _: Principal = PRINCIPAL_DEPENDENCY) -> dict[str, Any]:
    with _connect() as conn:
        result = _case_detail(conn, str(case_id))
        conn.rollback()
    if result is None:
        raise HTTPException(status_code=404, detail="decision case not found")
    return result


@app.post("/v1/cases/{case_id}/actions")
def case_action(
    case_id: UUID,
    body: ActionRequest,
    principal: Principal = PRINCIPAL_DEPENDENCY,
) -> dict[str, Any]:
    action = body.action.strip().lower().replace("_", "-")
    _require_action(principal, action)
    with _connect() as conn:
        target = _transition_case(
            conn, str(case_id), action, principal, body.note.strip()
        )
        conn.commit()
        result = _case_detail(conn, str(case_id))
        conn.rollback()
    return {
        "status": "PASS",
        "case_id": str(case_id),
        "new_status": target,
        "case": result,
    }


@app.get("/workbench", response_class=HTMLResponse)
def workbench() -> str:
    return WORKBENCH_PATH.read_text(encoding="utf-8")
