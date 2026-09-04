from __future__ import annotations

import json
from pathlib import Path

import pytest

from pharmstock.ml.stage7k5 import (
    EXPIRY_ALERT_TOPIC,
    REORDER_RECOMMENDATION_TOPIC,
    STOCKOUT_PREDICTION_TOPIC,
)
from pharmstock.onprem.stage7l import (
    ACTIONABLE_ML_TOPICS,
    STAGE7L_VERSION,
    decision_case_id,
    decode_ml_decision,
    next_status,
    normalize_reorder_units,
    stage7l_contract,
)
from scripts.run_checkpoint import checkpoint_command


def _base_payload(model_key: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "stage": "7K.5",
        "model_key": model_key,
        "model_version": "99",
        "prediction_event_id": "pred-123",
        "acceptance_smoke": False,
        "action_required": True,
    }
    if model_key in {"stockout_risk", "reorder_recommendation"}:
        payload["branch_id"] = "11111111-1111-1111-1111-111111111111"
        payload["product_id"] = "22222222-2222-2222-2222-222222222222"
    if model_key == "expiry_slow_moving_risk":
        payload["branch_id"] = "11111111-1111-1111-1111-111111111111"
        payload["product_id"] = "22222222-2222-2222-2222-222222222222"
        payload["batch_id"] = "33333333-3333-3333-3333-333333333333"
    return payload


def test_stage7l_contract_enforces_human_governance_and_no_auto_po() -> None:
    contract = stage7l_contract()
    assert STAGE7L_VERSION == "0.36.0"
    assert contract["runtime"] == "GOVERNED_OPERATIONAL_DECISION_WORKFLOW"
    assert contract["governance"]["human_approval_required"] is True
    assert contract["governance"]["automatic_purchase_order_creation"] is False
    assert contract["governance"]["automatic_supplier_selection"] is False
    assert contract["governance"]["database_role_has_procurement_write"] is False
    assert contract["cloud_mutation"] is False
    assert contract["bigquery_write"] is False


def test_stage7l_consumes_only_actionable_ml_topics() -> None:
    assert set(ACTIONABLE_ML_TOPICS) == {
        STOCKOUT_PREDICTION_TOPIC,
        REORDER_RECOMMENDATION_TOPIC,
        EXPIRY_ALERT_TOPIC,
    }
    assert "pharmstock.ml.demand_forecasts" not in ACTIONABLE_ML_TOPICS
    assert "pharmstock.ml.model_events" not in ACTIONABLE_ML_TOPICS


def test_stage7l_decodes_topic_model_contract_and_entity_keys() -> None:
    stockout = _base_payload("stockout_risk")
    stockout.update({"severity": "HIGH", "probability": 0.02, "operating_threshold": 0.002})
    event = decode_ml_decision(json.dumps(stockout), topic=STOCKOUT_PREDICTION_TOPIC)
    assert event.decision_type == "STOCKOUT"
    assert event.severity == "HIGH"
    assert event.entity_key.startswith("11111111-")

    expiry = decode_ml_decision(
        _base_payload("expiry_slow_moving_risk"), topic=EXPIRY_ALERT_TOPIC
    )
    assert expiry.decision_type == "EXPIRY"
    assert expiry.entity_key.startswith("33333333-")

    with pytest.raises(ValueError, match="topic/model mismatch"):
        decode_ml_decision(stockout, topic=REORDER_RECOMMENDATION_TOPIC)


def test_stage7l_reorder_converts_continuous_model_output_to_whole_units() -> None:
    payload = _base_payload("reorder_recommendation")
    payload["recommended_order_units"] = 2.01
    event = decode_ml_decision(payload, topic=REORDER_RECOMMENDATION_TOPIC)
    assert event.recommended_units == 3
    assert normalize_reorder_units(0.0) == 0
    assert normalize_reorder_units(1.0) == 1
    assert normalize_reorder_units(1.0001) == 2


def test_stage7l_case_ids_are_deterministic_and_prediction_specific() -> None:
    first = decision_case_id("prediction-a", "REORDER")
    assert first == decision_case_id("prediction-a", "REORDER")
    assert first != decision_case_id("prediction-b", "REORDER")
    assert first != decision_case_id("prediction-a", "STOCKOUT")


def test_stage7l_state_machine_requires_reorder_for_draft_approval() -> None:
    assert next_status("OPEN", "acknowledge", "STOCKOUT") == "ACKNOWLEDGED"
    assert next_status("ACKNOWLEDGED", "close", "EXPIRY") == "CLOSED"
    assert next_status("OPEN", "approve-draft", "REORDER") == "APPROVED_DRAFT"
    with pytest.raises(ValueError, match="only for REORDER"):
        next_status("OPEN", "approve-draft", "STOCKOUT")
    with pytest.raises(ValueError, match="invalid transition"):
        next_status("CLOSED", "acknowledge", "REORDER")


def test_stage7l_schema_is_isolated_and_database_blocks_procurement_execution() -> None:
    sql = Path("infra/docker/postgres/sql/010_stage7l_governed_decisions.sql").read_text(
        encoding="utf-8"
    )
    assert "CREATE SCHEMA IF NOT EXISTS decision_ops" in sql
    assert "CREATE TABLE IF NOT EXISTS decision_ops.ml_event_inbox" in sql
    assert "CREATE TABLE IF NOT EXISTS decision_ops.ml_event_quarantine" in sql
    assert "CREATE TABLE IF NOT EXISTS decision_ops.decision_case" in sql
    assert "CREATE TABLE IF NOT EXISTS decision_ops.replenishment_draft" in sql
    assert "CREATE TABLE IF NOT EXISTS decision_ops.decision_audit" in sql
    assert "CREATE ROLE pharmstock_decision LOGIN" in sql
    assert "GRANT SELECT ON mlops.prediction_event TO pharmstock_decision" in sql
    assert "REVOKE INSERT, UPDATE, DELETE ON procurement.purchase_order" in sql
    assert "decision_ops schema must not be part of pharmstock_cdc_publication" in sql
    assert "GRANT INSERT ON procurement.purchase_order" not in sql


def test_stage7l_worker_bootstraps_non_smoke_state_and_closes_model_cleared_cases() -> None:
    source = Path("operations/stage7l/worker.py").read_text(encoding="utf-8")
    assert "_latest_non_smoke_events" in source
    assert "acceptance_smoke" in source
    assert "MODEL_CLEARED" in source
    assert 'str(case["status"]) == "APPROVED_DRAFT"' in source
    assert "bootstrap_current_state(conn)" in source


def test_stage7l_worker_uses_durable_inbox_quarantine_and_manual_offsets() -> None:
    source = Path("operations/stage7l/worker.py").read_text(encoding="utf-8")
    assert "decision_ops.ml_event_inbox" in source
    assert "decision_ops.ml_event_quarantine" in source
    assert 'outcome="ALREADY_APPLIED"' in source
    assert '"enable.auto.commit": False' in source
    assert "consumer.commit(message=message, asynchronous=False)" in source
    assert "get_watermark_offsets" in source
    assert 'source = "COMMITTED"' in source
    assert 'source = "HIGH_WATERMARK"' in source


def test_stage7l_acceptance_smoke_is_ignored_and_governance_smoke_rolls_back() -> None:
    source = Path("operations/stage7l/worker.py").read_text(encoding="utf-8")
    assert 'outcome="IGNORED_SMOKE"' in source
    assert "conn.rollback()" in source
    assert "has_table_privilege" in source
    assert "automatic_po_allowed" in source
    assert "supplier_selected" in source




def test_stage7l_role_safety_uses_catalog_oids_without_procurement_schema_access() -> None:
    source = Path("operations/stage7l/worker.py").read_text(encoding="utf-8")
    assert "pg_catalog.pg_namespace" in source
    assert "pg_catalog.pg_class" in source
    assert "has_schema_privilege(current_user, schema_oid, 'USAGE')" in source
    assert "has_table_privilege(current_user, purchase_order_oid, 'INSERT')" in source
    assert "has_table_privilege(current_user, goods_receipt_oid, 'INSERT')" in source
    assert "'procurement.purchase_order', 'INSERT'" not in source

def test_stage7l_worker_never_writes_procurement_purchase_orders() -> None:
    source = Path("operations/stage7l/worker.py").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "insert into procurement.purchase_order" not in lowered
    assert "update procurement.purchase_order" not in lowered
    assert "delete from procurement.purchase_order" not in lowered
    assert "insert into procurement.goods_receipt" not in lowered


def test_stage7l_compose_uses_least_privilege_role_and_real_healthcheck() -> None:
    compose = Path("infra/docker/docker-compose.stage7l.yml").read_text(encoding="utf-8")
    assert "pharmstock-stage7l-workflow:0.36.0" in compose
    assert "PHARMSTOCK_STAGE7L_POSTGRES_USER: pharmstock_decision" in compose
    assert "PHARMSTOCK_DECISION_PASSWORD" in compose
    assert "stage7k5-online:" in compose
    assert "condition: service_healthy" in compose
    assert "--healthcheck" in compose
    assert "PHARMSTOCK_BQ_PROJECT" not in compose


def test_stage7l_runner_requires_accepted_stage7k5_and_reports_governance_markers() -> None:
    source = Path("scripts/run_stage7l.py").read_text(encoding="utf-8")
    assert "artifacts/stage7k5/stage7k5_report.json" in source
    assert "Stage 7K.5 worker was not HEALTHY" in source
    assert "Automatic PO creation:   BLOCKED" in source
    assert "STAGE_7L_GOVERNANCE_STATUS=PASS" in source
    assert "STAGE_7L_STATUS=PASS" in source


def test_stage7l_checkpoint_is_registered() -> None:
    assert checkpoint_command("7l")[1:] == ["scripts/run_stage7l.py"]
