"""Stage 7L governed operational decision-workflow worker."""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid5

from pharmstock.onprem.stage7l import (
    ACTIONABLE_ML_TOPICS,
    DECISION_NAMESPACE,
    MlDecisionEvent,
    config_from_environment,
    decision_case_id,
    decode_ml_decision,
    next_status,
    workflow_event_hash,
)

ARTIFACT_ROOT = Path(os.getenv("PHARMSTOCK_STAGE7L_ARTIFACT_ROOT", "artifacts/stage7l"))
HEARTBEAT_PATH = ARTIFACT_ROOT / "worker_heartbeat.json"
BOOTSTRAP_REPORT_PATH = ARTIFACT_ROOT / "bootstrap_report.json"
SMOKE_REPORT_PATH = ARTIFACT_ROOT / "smoke_report.json"


class Stage7LRuntimeError(RuntimeError):
    pass


@dataclass(slots=True)
class WorkerStats:
    processed_events: int = 0
    duplicate_events: int = 0
    ignored_smoke_events: int = 0
    ignored_non_actionable: int = 0
    quarantined_events: int = 0
    case_changes: int = 0
    retry_attempt: int = 0
    last_error: str | None = None
    last_prediction_event_id: str | None = None


def _pg_connect():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ModuleNotFoundError as exc:
        raise Stage7LRuntimeError("psycopg is required by the Stage 7L worker") from exc
    return psycopg.connect(
        host=os.getenv("PHARMSTOCK_POSTGRES_HOST", "postgres"),
        port=int(os.getenv("PHARMSTOCK_POSTGRES_INTERNAL_PORT", "5432")),
        dbname=os.getenv("PHARMSTOCK_POSTGRES_DB", "pharmstock_ops"),
        user=os.getenv("PHARMSTOCK_STAGE7L_POSTGRES_USER", "pharmstock_decision"),
        password=os.getenv(
            "PHARMSTOCK_STAGE7L_POSTGRES_PASSWORD",
            "pharmstock_local_dev_decision",
        ),
        row_factory=dict_row,
        autocommit=False,
    )


def _jsonb(value: dict[str, Any]):
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def _kafka_admin(bootstrap: str):
    try:
        from confluent_kafka.admin import AdminClient
    except ModuleNotFoundError as exc:
        raise Stage7LRuntimeError("confluent-kafka is required by Stage 7L") from exc
    return AdminClient({"bootstrap.servers": bootstrap, "client.id": "pharmstock-stage7l-admin"})


def _ensure_source_topics(bootstrap: str) -> tuple[str, ...]:
    metadata = _kafka_admin(bootstrap).list_topics(timeout=10)
    missing = [topic for topic in ACTIONABLE_ML_TOPICS if topic not in metadata.topics]
    if missing:
        raise Stage7LRuntimeError(f"Stage 7L source topics are missing: {missing}")
    return ACTIONABLE_ML_TOPICS


def _consumer(bootstrap: str, group: str):
    try:
        from confluent_kafka import Consumer
    except ModuleNotFoundError as exc:
        raise Stage7LRuntimeError("confluent-kafka is required by Stage 7L") from exc
    return Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": group,
            "client.id": "pharmstock-stage7l-workflow",
            "enable.auto.commit": False,
            "auto.offset.reset": "latest",
            "session.timeout.ms": 30000,
            "max.poll.interval.ms": 900000,
        }
    )


def _latest_non_smoke_events(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT DISTINCT ON (model_key, entity_key)
            prediction_event_id, model_key, model_version, entity_key, output_topic, payload,
            created_at
        FROM mlops.prediction_event
        WHERE model_key IN (
            'stockout_risk', 'reorder_recommendation', 'expiry_slow_moving_risk'
        )
          AND COALESCE((payload ->> 'acceptance_smoke')::boolean, false) = false
        ORDER BY model_key, entity_key, created_at DESC, prediction_event_id DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _prediction_seen(conn, prediction_event_id: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM decision_ops.decision_evidence
        WHERE prediction_event_id = %s
        """,
        (prediction_event_id,),
    ).fetchone()
    return row is not None


def _active_case(conn, event: MlDecisionEvent) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT *
        FROM decision_ops.decision_case
        WHERE decision_type = %s
          AND entity_key = %s
          AND status IN ('OPEN', 'ACKNOWLEDGED', 'APPROVED_DRAFT')
        ORDER BY opened_at DESC
        LIMIT 1
        FOR UPDATE
        """,
        (event.decision_type, event.entity_key),
    ).fetchone()
    return None if row is None else dict(row)


def _audit(
    conn,
    *,
    case_id: str,
    action: str,
    from_status: str | None,
    to_status: str,
    actor_type: str,
    actor_id: str,
    note: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO decision_ops.decision_audit (
            case_id, action, from_status, to_status, actor_type, actor_id, note
        ) VALUES (%s::uuid, %s, %s, %s, %s, %s, %s)
        """,
        (case_id, action, from_status, to_status, actor_type, actor_id, note),
    )


def _insert_evidence(conn, case_id: str, event: MlDecisionEvent) -> None:
    conn.execute(
        """
        INSERT INTO decision_ops.decision_evidence (
            prediction_event_id, case_id, model_key, model_version, severity,
            action_required, recommended_units, probability, threshold, payload
        ) VALUES (%s, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (prediction_event_id) DO NOTHING
        """,
        (
            event.prediction_event_id,
            case_id,
            event.model_key,
            event.model_version,
            event.severity,
            event.action_required,
            event.recommended_units,
            event.probability,
            event.threshold,
            _jsonb(event.payload),
        ),
    )


def _create_case(conn, event: MlDecisionEvent, source_mode: str) -> str:
    case_id = str(decision_case_id(event.prediction_event_id, event.decision_type))
    conn.execute(
        """
        INSERT INTO decision_ops.decision_case (
            case_id, decision_type, entity_key, branch_id, product_id, batch_id,
            status, severity, action_required, recommended_units,
            latest_prediction_event_id, source_mode
        ) VALUES (
            %s::uuid, %s, %s, %s::uuid, %s::uuid, %s::uuid,
            'OPEN', %s, %s, %s, %s, %s
        )
        """,
        (
            case_id,
            event.decision_type,
            event.entity_key,
            event.branch_id,
            event.product_id,
            event.batch_id,
            event.severity,
            event.action_required,
            event.recommended_units,
            event.prediction_event_id,
            source_mode,
        ),
    )
    if event.decision_type == "REORDER":
        if event.branch_id is None or event.product_id is None or not event.recommended_units:
            raise Stage7LRuntimeError("REORDER case is missing branch/product/recommended units")
        draft_id = str(uuid5(DECISION_NAMESPACE, f"draft|{case_id}"))
        conn.execute(
            """
            INSERT INTO decision_ops.replenishment_draft (
                draft_id, case_id, branch_id, product_id, recommended_units
            ) VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s)
            """,
            (
                draft_id,
                case_id,
                event.branch_id,
                event.product_id,
                event.recommended_units,
            ),
        )
    _insert_evidence(conn, case_id, event)
    _audit(
        conn,
        case_id=case_id,
        action="CASE_OPENED_FROM_ML",
        from_status=None,
        to_status="OPEN",
        actor_type="SYSTEM",
        actor_id="stage7l-workflow",
    )
    return case_id


def _update_active_case(conn, case: dict[str, Any], event: MlDecisionEvent) -> None:
    case_id = str(case["case_id"])
    conn.execute(
        """
        UPDATE decision_ops.decision_case
        SET severity = %s,
            action_required = %s,
            recommended_units = %s,
            latest_prediction_event_id = %s,
            updated_at = now()
        WHERE case_id = %s::uuid
        """,
        (
            event.severity,
            event.action_required,
            event.recommended_units,
            event.prediction_event_id,
            case_id,
        ),
    )
    if event.decision_type == "REORDER" and case["status"] != "APPROVED_DRAFT":
        conn.execute(
            """
            UPDATE decision_ops.replenishment_draft
            SET recommended_units = %s, updated_at = now()
            WHERE case_id = %s::uuid AND draft_status = 'PENDING_REVIEW'
            """,
            (event.recommended_units, case_id),
        )
    _insert_evidence(conn, case_id, event)


def _close_if_model_cleared(
    conn, case: dict[str, Any], event: MlDecisionEvent
) -> bool:
    case_id = str(case["case_id"])
    _insert_evidence(conn, case_id, event)
    if str(case["status"]) == "APPROVED_DRAFT":
        conn.execute(
            """
            UPDATE decision_ops.decision_case
            SET latest_prediction_event_id = %s,
                severity = %s,
                action_required = false,
                updated_at = now()
            WHERE case_id = %s::uuid
            """,
            (event.prediction_event_id, event.severity, case_id),
        )
        return True
    previous = str(case["status"])
    conn.execute(
        """
        UPDATE decision_ops.decision_case
        SET status = 'CLOSED',
            severity = %s,
            action_required = false,
            latest_prediction_event_id = %s,
            resolution_code = 'MODEL_CLEARED',
            closed_at = now(),
            updated_at = now()
        WHERE case_id = %s::uuid
        """,
        (event.severity, event.prediction_event_id, case_id),
    )
    if event.decision_type == "REORDER":
        conn.execute(
            """
            UPDATE decision_ops.replenishment_draft
            SET draft_status = 'CLOSED', updated_at = now()
            WHERE case_id = %s::uuid AND draft_status = 'PENDING_REVIEW'
            """,
            (case_id,),
        )
    _audit(
        conn,
        case_id=case_id,
        action="MODEL_CLEARED",
        from_status=previous,
        to_status="CLOSED",
        actor_type="SYSTEM",
        actor_id="stage7l-workflow",
    )
    return True


def _apply_event(conn, event: MlDecisionEvent, source_mode: str) -> bool:
    if event.acceptance_smoke:
        return False
    if _prediction_seen(conn, event.prediction_event_id):
        return False
    case = _active_case(conn, event)
    if event.action_required:
        if case is None:
            _create_case(conn, event, source_mode)
        else:
            _update_active_case(conn, case, event)
        return True
    if case is None:
        return False
    return _close_if_model_cleared(conn, case, event)


def _insert_inbox(
    conn,
    *,
    event: MlDecisionEvent,
    topic: str,
    partition: int,
    offset: int,
    outcome: str,
) -> bool:
    cursor = conn.execute(
        """
        INSERT INTO decision_ops.ml_event_inbox (
            prediction_event_id, topic, partition_id, offset_value, model_key,
            entity_key, payload, outcome
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (prediction_event_id) DO NOTHING
        """,
        (
            event.prediction_event_id,
            topic,
            partition,
            offset,
            event.model_key,
            event.entity_key,
            _jsonb(event.payload),
            outcome,
        ),
    )
    return cursor.rowcount == 1


def _quarantine(conn, message, exc: Exception) -> None:
    raw_value = message.value()
    if isinstance(raw_value, bytes):
        raw_payload = raw_value.decode("utf-8", errors="replace")
    elif raw_value is None:
        raw_payload = None
    else:
        raw_payload = str(raw_value)
    event_hash = workflow_event_hash(message.topic(), message.partition(), message.offset())
    conn.execute(
        """
        INSERT INTO decision_ops.ml_event_quarantine (
            workflow_event_hash, topic, partition_id, offset_value, raw_payload,
            error_class, error_message
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (workflow_event_hash) DO NOTHING
        """,
        (
            event_hash,
            message.topic(),
            message.partition(),
            message.offset(),
            raw_payload,
            type(exc).__name__,
            str(exc),
        ),
    )
    conn.commit()


def _process_message(conn, message, stats: WorkerStats) -> None:
    try:
        event = decode_ml_decision(message.value(), topic=message.topic())
    except Exception as exc:
        conn.rollback()
        _quarantine(conn, message, exc)
        stats.quarantined_events += 1
        return

    existing = conn.execute(
        """
        SELECT outcome
        FROM decision_ops.ml_event_inbox
        WHERE prediction_event_id = %s
        """,
        (event.prediction_event_id,),
    ).fetchone()
    if existing is not None:
        stats.duplicate_events += 1
        conn.rollback()
        return

    if event.acceptance_smoke:
        _insert_inbox(
            conn,
            event=event,
            topic=message.topic(),
            partition=message.partition(),
            offset=message.offset(),
            outcome="IGNORED_SMOKE",
        )
        conn.commit()
        stats.ignored_smoke_events += 1
        stats.processed_events += 1
        stats.last_prediction_event_id = event.prediction_event_id
        return

    if _prediction_seen(conn, event.prediction_event_id):
        _insert_inbox(
            conn,
            event=event,
            topic=message.topic(),
            partition=message.partition(),
            offset=message.offset(),
            outcome="ALREADY_APPLIED",
        )
        conn.commit()
        stats.duplicate_events += 1
        stats.processed_events += 1
        stats.last_prediction_event_id = event.prediction_event_id
        return

    changed = _apply_event(conn, event, "KAFKA")
    outcome = "PROCESSED" if changed else "IGNORED_NON_ACTIONABLE"
    _insert_inbox(
        conn,
        event=event,
        topic=message.topic(),
        partition=message.partition(),
        offset=message.offset(),
        outcome=outcome,
    )
    conn.commit()
    stats.processed_events += 1
    stats.case_changes += int(changed)
    stats.ignored_non_actionable += int(not changed)
    stats.last_prediction_event_id = event.prediction_event_id


def bootstrap_current_state(conn) -> dict[str, int]:
    rows = _latest_non_smoke_events(conn)
    changed = 0
    actionable = 0
    for row in rows:
        event = decode_ml_decision(dict(row["payload"]), topic=str(row["output_topic"]))
        actionable += int(event.action_required)
        changed += int(_apply_event(conn, event, "BOOTSTRAP"))
    conn.commit()
    counts = conn.execute(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE status IN ('OPEN', 'ACKNOWLEDGED', 'APPROVED_DRAFT')
            )::integer AS active_cases,
            COUNT(*) FILTER (WHERE status = 'APPROVED_DRAFT')::integer AS approved_drafts
        FROM decision_ops.decision_case
        """
    ).fetchone()
    return {
        "current_ml_entities": len(rows),
        "actionable_current_entities": actionable,
        "bootstrap_case_changes": changed,
        "active_cases": int(counts["active_cases"]),
        "approved_drafts": int(counts["approved_drafts"]),
    }


def _role_safety(conn) -> dict[str, bool]:
    row = conn.execute(
        """
        WITH procurement_schema AS (
            SELECT oid AS schema_oid
            FROM pg_catalog.pg_namespace
            WHERE nspname = 'procurement'
        ),
        target_oids AS (
            SELECT
                ps.schema_oid,
                (
                    SELECT c.oid
                    FROM pg_catalog.pg_class AS c
                    WHERE c.relnamespace = ps.schema_oid
                      AND c.relname = 'purchase_order'
                    LIMIT 1
                ) AS purchase_order_oid,
                (
                    SELECT c.oid
                    FROM pg_catalog.pg_class AS c
                    WHERE c.relnamespace = ps.schema_oid
                      AND c.relname = 'goods_receipt'
                    LIMIT 1
                ) AS goods_receipt_oid
            FROM procurement_schema AS ps
        )
        SELECT
            purchase_order_oid IS NULL AS purchase_order_missing,
            goods_receipt_oid IS NULL AS goods_receipt_missing,
            COALESCE(
                has_schema_privilege(current_user, schema_oid, 'USAGE'), false
            ) AS can_use_procurement_schema,
            COALESCE(
                has_table_privilege(current_user, purchase_order_oid, 'INSERT'), false
            ) AS can_insert_po,
            COALESCE(
                has_table_privilege(current_user, purchase_order_oid, 'UPDATE'), false
            ) AS can_update_po,
            COALESCE(
                has_table_privilege(current_user, goods_receipt_oid, 'INSERT'), false
            ) AS can_insert_receipt
        FROM target_oids
        """
    ).fetchone()
    if row is None:
        return {
            "procurement_schema_missing": True,
            "purchase_order_missing": True,
            "goods_receipt_missing": True,
        }
    return {key: bool(value) for key, value in dict(row).items()}


def bootstrap_only() -> None:
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:19092")
    topics = _ensure_source_topics(bootstrap)
    with _pg_connect() as conn:
        safety = _role_safety(conn)
        if any(safety.values()):
            raise Stage7LRuntimeError(f"decision role has unsafe procurement privilege: {safety}")
        state = bootstrap_current_state(conn)
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "PASS",
        "source_topics": list(topics),
        "state": state,
        "role_safety": safety,
        "automatic_purchase_order_creation": False,
        "cloud_mutation": False,
    }
    BOOTSTRAP_REPORT_PATH.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    print("=== PharmStock Stage 7L / Governed Workflow Bootstrap ===")
    print(f"ML source topics:        {len(topics)}")
    print(f"Current ML entities:     {state['current_ml_entities']}")
    print(f"Active decision cases:   {state['active_cases']}")
    print("Purchase-order writes:   BLOCKED BY DATABASE ROLE")
    print("Cloud mutation:          NO")
    print("STAGE_7L_BOOTSTRAP_STATUS=PASS")


def _smoke_seed(conn) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT prediction_event_id, payload
        FROM mlops.prediction_event
        WHERE model_key = 'reorder_recommendation'
        ORDER BY created_at DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise Stage7LRuntimeError("Stage 7L smoke requires one Stage 7K.5 reorder prediction")
    return dict(row)


def smoke() -> None:
    with _pg_connect() as conn:
        safety = _role_safety(conn)
        if any(safety.values()):
            raise Stage7LRuntimeError(f"decision role has unsafe procurement privilege: {safety}")
        seed = _smoke_seed(conn)
        payload = dict(seed["payload"])
        payload["acceptance_smoke"] = False
        payload["action_required"] = True
        payload["recommended_order_units"] = max(
            float(payload.get("recommended_order_units") or 0.0), 1.0
        )
        base_event = decode_ml_decision(payload, topic="pharmstock.ml.reorder_recommendations")
        smoke_key = f"__stage7l_smoke__|{time.time_ns()}"
        smoke_case_id = str(uuid5(DECISION_NAMESPACE, smoke_key))
        conn.execute(
            """
            INSERT INTO decision_ops.decision_case (
                case_id, decision_type, entity_key, branch_id, product_id,
                status, severity, action_required, recommended_units,
                latest_prediction_event_id, source_mode
            ) VALUES (
                %s::uuid, 'REORDER', %s, %s::uuid, %s::uuid,
                'OPEN', 'WATCH', true, %s, %s, 'BOOTSTRAP'
            )
            """,
            (
                smoke_case_id,
                smoke_key,
                base_event.branch_id,
                base_event.product_id,
                base_event.recommended_units,
                base_event.prediction_event_id,
            ),
        )
        draft_id = str(uuid5(DECISION_NAMESPACE, f"draft|{smoke_case_id}"))
        conn.execute(
            """
            INSERT INTO decision_ops.replenishment_draft (
                draft_id, case_id, branch_id, product_id, recommended_units
            ) VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s)
            """,
            (
                draft_id,
                smoke_case_id,
                base_event.branch_id,
                base_event.product_id,
                base_event.recommended_units,
            ),
        )
        _transition_case_tx(
            conn,
            smoke_case_id,
            action="acknowledge",
            actor="stage7l-smoke",
            note="transactional acceptance smoke",
        )
        _transition_case_tx(
            conn,
            smoke_case_id,
            action="approve-draft",
            actor="stage7l-smoke",
            note="approval must remain a non-executable draft",
        )
        row = conn.execute(
            """
            SELECT c.status, d.draft_status, d.automatic_po_allowed, d.supplier_selected
            FROM decision_ops.decision_case c
            JOIN decision_ops.replenishment_draft d ON d.case_id = c.case_id
            WHERE c.case_id = %s::uuid
            """,
            (smoke_case_id,),
        ).fetchone()
        if row is None or row["status"] != "APPROVED_DRAFT":
            raise Stage7LRuntimeError("Stage 7L smoke did not reach APPROVED_DRAFT")
        if row["draft_status"] != "APPROVED":
            raise Stage7LRuntimeError("Stage 7L smoke replenishment draft was not approved")
        if bool(row["automatic_po_allowed"]) or bool(row["supplier_selected"]):
            raise Stage7LRuntimeError("Stage 7L smoke violated non-execution governance")
        conn.rollback()

    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "PASS",
        "transaction_rolled_back": True,
        "case_lifecycle": ["OPEN", "ACKNOWLEDGED", "APPROVED_DRAFT"],
        "purchase_order_write_privilege": False,
        "automatic_po_allowed": False,
        "supplier_selected": False,
        "cloud_mutation": False,
    }
    SMOKE_REPORT_PATH.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    print("=== PharmStock Stage 7L / Governance Smoke ===")
    print("Case lifecycle:          OPEN -> ACKNOWLEDGED -> APPROVED_DRAFT")
    print("Smoke transaction:       ROLLED BACK")
    print("Purchase-order privilege:BLOCKED")
    print("Supplier selection:      NONE")
    print("STAGE_7L_SMOKE_STATUS=PASS")


def _transition_case_tx(conn, case_id: str, *, action: str, actor: str, note: str) -> str:
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
        raise Stage7LRuntimeError(f"decision case not found: {case_id}")
    current = str(row["status"])
    decision_type = str(row["decision_type"])
    target = next_status(current, action, decision_type)
    timestamp_column = {
        "ACKNOWLEDGED": "acknowledged_at",
        "APPROVED_DRAFT": "decided_at",
        "REJECTED": "decided_at",
        "CLOSED": "closed_at",
    }[target]
    conn.execute(
        f"""
        UPDATE decision_ops.decision_case
        SET status = %s, {timestamp_column} = now(), updated_at = now()
        WHERE case_id = %s::uuid
        """,
        (target, case_id),
    )
    if decision_type == "REORDER":
        if target == "APPROVED_DRAFT":
            conn.execute(
                """
                UPDATE decision_ops.replenishment_draft
                SET draft_status = 'APPROVED', approved_by = %s,
                    approved_at = now(), updated_at = now()
                WHERE case_id = %s::uuid
                """,
                (actor, case_id),
            )
        elif target == "REJECTED":
            conn.execute(
                """
                UPDATE decision_ops.replenishment_draft
                SET draft_status = 'REJECTED', updated_at = now()
                WHERE case_id = %s::uuid
                """,
                (case_id,),
            )
        elif target == "CLOSED":
            conn.execute(
                """
                UPDATE decision_ops.replenishment_draft
                SET draft_status = 'CLOSED', updated_at = now()
                WHERE case_id = %s::uuid
                """,
                (case_id,),
            )
    _audit(
        conn,
        case_id=case_id,
        action=action.upper().replace("-", "_"),
        from_status=current,
        to_status=target,
        actor_type="HUMAN",
        actor_id=actor,
        note=note,
    )
    return target


def transition_case(case_id: str, action: str, actor: str, note: str) -> None:
    with _pg_connect() as conn:
        target = _transition_case_tx(conn, case_id, action=action, actor=actor, note=note)
        conn.commit()
    print(f"STAGE_7L_CASE_TRANSITION_STATUS=PASS case_id={case_id} status={target}")


def list_open_cases(limit: int) -> None:
    with _pg_connect() as conn:
        rows = conn.execute(
            """
            SELECT case_id::text, decision_type, entity_key, status, severity,
                   recommended_units, opened_at, updated_at
            FROM decision_ops.decision_case
            WHERE status IN ('OPEN', 'ACKNOWLEDGED', 'APPROVED_DRAFT')
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
            (max(1, min(limit, 500)),),
        ).fetchall()
    print(json.dumps([dict(row) for row in rows], default=str, indent=2))


def _metrics(conn) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM decision_ops.decision_case
             WHERE status IN ('OPEN', 'ACKNOWLEDGED', 'APPROVED_DRAFT'))::integer
                AS active_cases,
            (SELECT COUNT(*) FROM decision_ops.replenishment_draft
             WHERE draft_status = 'APPROVED')::integer AS approved_drafts,
            (SELECT COUNT(*) FROM decision_ops.ml_event_quarantine)::integer
                AS quarantine_rows,
            (SELECT COUNT(*) FROM decision_ops.ml_event_inbox)::integer AS inbox_rows
        """
    ).fetchone()
    return {key: int(value) for key, value in dict(row).items()}


def _write_heartbeat(stats: WorkerStats, assignment: list[dict[str, int]]) -> None:
    with _pg_connect() as conn:
        metrics = _metrics(conn)
        safety = _role_safety(conn)
        conn.rollback()
    report = {
        "status": "HEALTHY" if not any(safety.values()) else "UNHEALTHY",
        "generated_at": datetime.now(UTC).isoformat(),
        "assignment": assignment,
        "metrics": metrics,
        "role_safety": safety,
        "stats": {
            "processed_events": stats.processed_events,
            "duplicate_events": stats.duplicate_events,
            "ignored_smoke_events": stats.ignored_smoke_events,
            "ignored_non_actionable": stats.ignored_non_actionable,
            "quarantined_events": stats.quarantined_events,
            "case_changes": stats.case_changes,
            "retry_attempt": stats.retry_attempt,
            "last_error": stats.last_error,
            "last_prediction_event_id": stats.last_prediction_event_id,
        },
    }
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def _assigned_partitions(consumer, partitions, assignment_state: dict[str, Any]) -> None:
    committed = consumer.committed(partitions, timeout=10)
    adjusted = []
    summary = []
    for partition, stored in zip(partitions, committed, strict=True):
        if stored.offset >= 0:
            start_offset = int(stored.offset)
            source = "COMMITTED"
        else:
            _, high = consumer.get_watermark_offsets(partition, timeout=10)
            start_offset = int(high)
            source = "HIGH_WATERMARK"
        partition.offset = start_offset
        adjusted.append(partition)
        summary.append(
            {
                "topic": str(partition.topic),
                "partition": int(partition.partition),
                "offset": start_offset,
                "source": source,
            }
        )
    consumer.assign(adjusted)
    assignment_state["ready"] = True
    assignment_state["partitions"] = summary


def run_worker() -> None:
    config = config_from_environment()
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:19092")
    _ensure_source_topics(bootstrap)
    consumer = _consumer(bootstrap, config.consumer_group)
    assignment_state: dict[str, Any] = {"ready": False, "partitions": []}
    consumer.subscribe(
        list(ACTIONABLE_ML_TOPICS),
        on_assign=lambda c, p: _assigned_partitions(c, p, assignment_state),
    )

    prefetched = []
    deadline = time.monotonic() + 60
    while not assignment_state["ready"] and time.monotonic() < deadline:
        message = consumer.poll(1.0)
        if message is not None and message.error() is None:
            prefetched.append(message)
    if not assignment_state["ready"]:
        consumer.close()
        raise Stage7LRuntimeError("Kafka assignment did not become ready")

    with _pg_connect() as conn:
        bootstrap_current_state(conn)

    stats = WorkerStats()
    last_heartbeat = 0.0
    pending = list(prefetched)
    try:
        while True:
            message = pending.pop(0) if pending else consumer.poll(1.0)
            now = time.monotonic()
            if now - last_heartbeat >= 10:
                _write_heartbeat(stats, list(assignment_state["partitions"]))
                last_heartbeat = now
            if message is None:
                continue
            if message.error() is not None:
                stats.last_error = str(message.error())
                continue

            attempt = 0
            while True:
                try:
                    with _pg_connect() as conn:
                        _process_message(conn, message, stats)
                    consumer.commit(message=message, asynchronous=False)
                    stats.retry_attempt = 0
                    stats.last_error = None
                    break
                except Exception as exc:
                    attempt += 1
                    stats.retry_attempt = attempt
                    stats.last_error = str(exc)
                    delay = min(2 ** min(attempt - 1, 8), config.max_processing_backoff_seconds)
                    _write_heartbeat(stats, list(assignment_state["partitions"]))
                    time.sleep(delay)
    finally:
        consumer.close()


def healthcheck() -> None:
    max_age = int(os.getenv("PHARMSTOCK_STAGE7L_HEARTBEAT_MAX_AGE_SECONDS", "45"))
    if not HEARTBEAT_PATH.is_file():
        raise Stage7LRuntimeError("Stage 7L heartbeat is missing")
    heartbeat = json.loads(HEARTBEAT_PATH.read_text(encoding="utf-8"))
    generated_at = datetime.fromisoformat(str(heartbeat["generated_at"]))
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=UTC)
    heartbeat_age = (datetime.now(UTC) - generated_at).total_seconds()
    if heartbeat.get("status") != "HEALTHY" or heartbeat_age > max_age:
        raise Stage7LRuntimeError(
            "Stage 7L heartbeat unhealthy/stale: "
            f"status={heartbeat.get('status')} age={heartbeat_age:.1f}s"
        )
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:19092")
    _ensure_source_topics(bootstrap)
    with _pg_connect() as conn:
        conn.execute("SELECT 1").fetchone()
        safety = _role_safety(conn)
        conn.rollback()
    if any(safety.values()):
        raise Stage7LRuntimeError(f"unsafe procurement privilege detected: {safety}")
    print(
        "STAGE_7L_HEALTHCHECK_STATUS=PASS "
        f"heartbeat_age={heartbeat_age:.1f}s active={heartbeat['metrics']['active_cases']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="PharmStock Stage 7L decision workflow worker")
    parser.add_argument("--bootstrap-only", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--list-open", action="store_true")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--case-id")
    parser.add_argument(
        "--action", choices=("acknowledge", "approve-draft", "reject", "close")
    )
    parser.add_argument("--actor", default="local-operator")
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    if args.bootstrap_only:
        bootstrap_only()
        return
    if args.smoke:
        smoke()
        return
    if args.healthcheck:
        healthcheck()
        return
    if args.list_open:
        list_open_cases(args.limit)
        return
    if args.case_id or args.action:
        if not args.case_id or not args.action:
            parser.error("--case-id and --action must be supplied together")
        transition_case(args.case_id, args.action, args.actor, args.note)
        return
    run_worker()


if __name__ == "__main__":
    main()
