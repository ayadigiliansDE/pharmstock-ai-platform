"""Stage 7L governed operational decision-workflow contracts.

Stage 7L consumes actionable Stage 7K.5 prediction streams and turns them into
reviewable operational cases. It deliberately stops before supplier selection or
purchase-order creation. Human approval is a hard boundary, and the runtime role
has no write privilege on procurement.purchase_order.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID, uuid5

from pharmstock.ml.stage7k5 import (
    EXPIRY_ALERT_TOPIC,
    REORDER_RECOMMENDATION_TOPIC,
    STOCKOUT_PREDICTION_TOPIC,
)

STAGE7L_VERSION: Final[str] = "0.36.0"
DEFAULT_CONSUMER_GROUP: Final[str] = "pharmstock-stage7l-workflow-v1"
DEFAULT_MAX_PROCESSING_BACKOFF_SECONDS: Final[int] = 30
DEFAULT_HEARTBEAT_MAX_AGE_SECONDS: Final[int] = 45
DECISION_NAMESPACE: Final[UUID] = UUID("e61ea121-d6f7-4bd8-aec2-8ae6fc34a7db")

ACTIONABLE_ML_TOPICS: Final[tuple[str, ...]] = (
    STOCKOUT_PREDICTION_TOPIC,
    REORDER_RECOMMENDATION_TOPIC,
    EXPIRY_ALERT_TOPIC,
)

TOPIC_MODEL_KEY: Final[dict[str, str]] = {
    STOCKOUT_PREDICTION_TOPIC: "stockout_risk",
    REORDER_RECOMMENDATION_TOPIC: "reorder_recommendation",
    EXPIRY_ALERT_TOPIC: "expiry_slow_moving_risk",
}

MODEL_DECISION_TYPE: Final[dict[str, str]] = {
    "stockout_risk": "STOCKOUT",
    "reorder_recommendation": "REORDER",
    "expiry_slow_moving_risk": "EXPIRY",
}

ACTIVE_CASE_STATUSES: Final[frozenset[str]] = frozenset(
    {"OPEN", "ACKNOWLEDGED", "APPROVED_DRAFT"}
)


@dataclass(frozen=True, slots=True)
class Stage7LConfig:
    consumer_group: str
    max_processing_backoff_seconds: int

    def validate(self) -> None:
        if not self.consumer_group.strip():
            raise ValueError("PHARMSTOCK_STAGE7L_CONSUMER_GROUP cannot be empty")
        if self.max_processing_backoff_seconds < 1:
            raise ValueError("PHARMSTOCK_STAGE7L_MAX_PROCESSING_BACKOFF_SECONDS must be >= 1")


@dataclass(frozen=True, slots=True)
class MlDecisionEvent:
    prediction_event_id: str
    topic: str
    model_key: str
    model_version: str
    decision_type: str
    entity_key: str
    branch_id: str | None
    product_id: str | None
    batch_id: str | None
    action_required: bool
    severity: str
    recommended_units: int | None
    probability: float | None
    threshold: float | None
    acceptance_smoke: bool
    payload: dict[str, Any]


def config_from_environment() -> Stage7LConfig:
    config = Stage7LConfig(
        consumer_group=os.getenv(
            "PHARMSTOCK_STAGE7L_CONSUMER_GROUP", DEFAULT_CONSUMER_GROUP
        ).strip(),
        max_processing_backoff_seconds=int(
            os.getenv(
                "PHARMSTOCK_STAGE7L_MAX_PROCESSING_BACKOFF_SECONDS",
                str(DEFAULT_MAX_PROCESSING_BACKOFF_SECONDS),
            )
        ),
    )
    config.validate()
    return config


def _finite_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def normalize_reorder_units(value: Any) -> int:
    """Convert a continuous model recommendation to whole physical units conservatively."""

    numeric = _finite_float(value)
    if numeric is None or numeric <= 0:
        return 0
    return int(math.ceil(numeric))


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ValueError(f"missing required field: {key}")
    return value


def _entity_key(model_key: str, payload: dict[str, Any]) -> str:
    if model_key in {"stockout_risk", "reorder_recommendation"}:
        return f"{_required_text(payload, 'branch_id')}|{_required_text(payload, 'product_id')}"
    if model_key == "expiry_slow_moving_risk":
        return _required_text(payload, "batch_id")
    raise ValueError(f"unsupported Stage 7L model_key: {model_key!r}")


def decode_ml_decision(payload: bytes | str | dict[str, Any], *, topic: str) -> MlDecisionEvent:
    if topic not in TOPIC_MODEL_KEY:
        raise ValueError(f"unsupported Stage 7L source topic: {topic!r}")
    if isinstance(payload, dict):
        body = dict(payload)
    else:
        raw = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        decoded = json.loads(raw)
        if not isinstance(decoded, dict):
            raise ValueError("ML decision payload must decode to an object")
        body = decoded

    if str(body.get("stage", "")) != "7K.5":
        raise ValueError("Stage 7L accepts only Stage 7K.5 decision events")
    expected_model = TOPIC_MODEL_KEY[topic]
    model_key = _required_text(body, "model_key")
    if model_key != expected_model:
        raise ValueError(
            f"ML topic/model mismatch: topic={topic!r} model_key={model_key!r}"
        )
    prediction_id = _required_text(body, "prediction_event_id")
    model_version = _required_text(body, "model_version")
    decision_type = MODEL_DECISION_TYPE[model_key]
    entity_key = _entity_key(model_key, body)
    branch_id = None if body.get("branch_id") is None else str(body["branch_id"])
    product_id = None if body.get("product_id") is None else str(body["product_id"])
    batch_id = None if body.get("batch_id") is None else str(body["batch_id"])
    action_required = bool(body.get("action_required", False))
    recommended_units = None
    if model_key == "reorder_recommendation":
        recommended_units = normalize_reorder_units(body.get("recommended_order_units"))
        action_required = action_required and recommended_units > 0

    if model_key == "stockout_risk":
        severity = str(body.get("severity") or "NORMAL").upper()
    elif model_key == "expiry_slow_moving_risk":
        severity = "HIGH" if action_required else "NORMAL"
    else:
        severity = "WATCH" if action_required else "NORMAL"

    return MlDecisionEvent(
        prediction_event_id=prediction_id,
        topic=topic,
        model_key=model_key,
        model_version=model_version,
        decision_type=decision_type,
        entity_key=entity_key,
        branch_id=branch_id,
        product_id=product_id,
        batch_id=batch_id,
        action_required=action_required,
        severity=severity,
        recommended_units=recommended_units,
        probability=_finite_float(body.get("probability")),
        threshold=_finite_float(body.get("operating_threshold")),
        acceptance_smoke=bool(body.get("acceptance_smoke", False)),
        payload=body,
    )


def decision_case_id(prediction_event_id: str, decision_type: str) -> UUID:
    return uuid5(DECISION_NAMESPACE, f"{decision_type}|{prediction_event_id}")


def workflow_event_hash(topic: str, partition: int, offset: int) -> str:
    raw = f"{topic}|{int(partition)}|{int(offset)}".encode()
    return hashlib.sha256(raw).hexdigest()


def next_status(current_status: str, action: str, decision_type: str) -> str:
    current = current_status.upper()
    normalized = action.strip().lower().replace("_", "-")
    if current == "OPEN":
        allowed = {
            "acknowledge": "ACKNOWLEDGED",
            "reject": "REJECTED",
            "close": "CLOSED",
        }
    elif current == "ACKNOWLEDGED":
        allowed = {"reject": "REJECTED", "close": "CLOSED"}
    elif current == "APPROVED_DRAFT":
        allowed = {"close": "CLOSED"}
    else:
        allowed = {}
    if normalized == "approve-draft":
        if decision_type != "REORDER":
            raise ValueError("approve-draft is allowed only for REORDER cases")
        if current not in {"OPEN", "ACKNOWLEDGED"}:
            raise ValueError(f"cannot approve draft from status {current}")
        return "APPROVED_DRAFT"
    if normalized not in allowed:
        raise ValueError(f"invalid transition: {current} --{normalized}--> ?")
    return allowed[normalized]


def stage7l_contract() -> dict[str, object]:
    return {
        "stage": "7L",
        "version": STAGE7L_VERSION,
        "runtime": "GOVERNED_OPERATIONAL_DECISION_WORKFLOW",
        "source_topics": list(ACTIONABLE_ML_TOPICS),
        "bootstrap": "LATEST_NON_SMOKE_ML_JOURNAL_THEN_KAFKA_ASSIGNED_HIGH_WATERMARK",
        "delivery": {
            "source_offsets": "MANUAL_COMMIT_AFTER_DURABLE_INBOX_AND_CASE_STATE",
            "prediction_event_deduplication": True,
            "durable_invalid_event_quarantine": True,
            "cross_system_exactly_once_claimed": False,
        },
        "governance": {
            "human_approval_required": True,
            "automatic_purchase_order_creation": False,
            "automatic_supplier_selection": False,
            "reorder_output": "APPROVED_DRAFT_ONLY",
            "database_role_has_procurement_write": False,
            "acceptance_smoke_creates_live_case": False,
        },
        "case_statuses": sorted(ACTIVE_CASE_STATUSES | {"REJECTED", "CLOSED"}),
        "cloud_mutation": False,
        "bigquery_write": False,
    }
