"""Evidence-grounded explanation layer for Stage 7O."""

from __future__ import annotations

from typing import Any


class EvidenceExplanationError(RuntimeError):
    """Raised when required evidence is unavailable or inconsistent."""


def _tool_data(
    plan: dict[str, Any],
    tool_name: str,
) -> dict[str, Any]:
    for item in plan.get("evidence", []):
        if item.get("tool") == tool_name:
            data = item.get("data")
            if isinstance(data, dict):
                return data

    return {}


def _first_item(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("items")

    if not isinstance(items, list) or not items:
        return {}

    first = items[0]
    return first if isinstance(first, dict) else {}


def explain_reorder_recommendation(
    plan: dict[str, Any],
) -> dict[str, Any]:
    inventory_payload = _tool_data(
        plan,
        "inventory_context",
    )
    ml_payload = _tool_data(
        plan,
        "ml_signals",
    )
    cases_payload = _tool_data(
        plan,
        "decision_cases",
    )

    inventory = _first_item(inventory_payload)

    ml_items = ml_payload.get("items", [])
    case_items = cases_payload.get("items", [])

    if not isinstance(ml_items, list):
        ml_items = []

    if not isinstance(case_items, list):
        case_items = []

    reorder_signal = next(
        (
            item
            for item in ml_items
            if isinstance(item, dict)
            and item.get("model_key") == "reorder_recommendation"
        ),
        {},
    )

    stockout_signal = next(
        (
            item
            for item in ml_items
            if isinstance(item, dict)
            and item.get("model_key") == "stockout_risk"
        ),
        {},
    )

    reorder_case = next(
        (
            item
            for item in case_items
            if isinstance(item, dict)
            and item.get("decision_type") == "REORDER"
        ),
        {},
    )

    if not reorder_signal:
        raise EvidenceExplanationError(
            "Reorder recommendation evidence is unavailable"
        )

    recommended_units = reorder_signal.get(
        "prediction_value"
    )

    facts = [
        {
            "fact": "model_recommendation",
            "value": recommended_units,
            "unit": "units",
            "model_version": reorder_signal.get(
                "model_version"
            ),
        },
        {
            "fact": "available_inventory",
            "value": inventory.get("available_units"),
            "unit": "units",
        },
        {
            "fact": "reorder_point",
            "value": inventory.get(
                "reorder_point_units"
            ),
            "unit": "units",
        },
        {
            "fact": "target_stock",
            "value": inventory.get(
                "target_stock_units"
            ),
            "unit": "units",
        },
        {
            "fact": "zero_stock",
            "value": inventory.get("zero_stock"),
        },
        {
            "fact": "below_reorder",
            "value": inventory.get(
                "below_reorder"
            ),
        },
        {
            "fact": "reorder_action_required",
            "value": reorder_signal.get(
                "action_required"
            ),
        },
    ]

    if stockout_signal:
        facts.extend(
            [
                {
                    "fact": "stockout_severity",
                    "value": stockout_signal.get(
                        "severity"
                    ),
                },
                {
                    "fact": "stockout_probability",
                    "value": stockout_signal.get(
                        "probability"
                    ),
                },
                {
                    "fact": "stockout_threshold",
                    "value": stockout_signal.get(
                        "threshold"
                    ),
                },
                {
                    "fact": "stockout_action_required",
                    "value": stockout_signal.get(
                        "action_required"
                    ),
                },
            ]
        )

    if reorder_case:
        facts.extend(
            [
                {
                    "fact": "decision_status",
                    "value": reorder_case.get("status"),
                },
                {
                    "fact": "approved_draft_units",
                    "value": reorder_case.get(
                        "recommended_units"
                    ),
                    "unit": "units",
                },
                {
                    "fact": "approval_required",
                    "value": reorder_case.get(
                        "approval_required"
                    ),
                },
                {
                    "fact": "supplier_selected",
                    "value": reorder_case.get(
                        "supplier_selected"
                    ),
                },
                {
                    "fact": "automatic_po_allowed",
                    "value": reorder_case.get(
                        "automatic_po_allowed"
                    ),
                },
            ]
        )

    exact_quantity_explainable = False

    limitations = [
        (
            "The available evidence supports the need for "
            "replenishment, but it does not expose feature "
            "attribution or a quantity formula sufficient to "
            f"prove why the recommendation is exactly "
            f"{recommended_units} units."
        ),
        (
            "The target-stock value must not be treated as the "
            "formula for the ML recommendation unless model "
            "evidence explicitly proves that relationship."
        ),
    ]

    return {
        "explanation_type": "REORDER_RECOMMENDATION",
        "branch": {
            "branch_id": inventory.get("branch_id"),
            "branch_code": inventory.get("branch_code"),
            "branch_name": inventory.get("branch_name"),
        },
        "product": {
            "product_id": inventory.get("product_id"),
            "trade_name_en": inventory.get(
                "trade_name_en"
            ),
            "scientific_name": inventory.get(
                "scientific_name"
            ),
        },
        "recommended_units": recommended_units,
        "exact_quantity_explainable": (
            exact_quantity_explainable
        ),
        "supported_interpretation": (
            "Current inventory conditions and the governed ML "
            "signals support a replenishment need. The exact "
            "recommended quantity is a model output and cannot "
            "be causally decomposed from the currently exposed "
            "evidence."
        ),
        "facts": facts,
        "limitations": limitations,
        "governance": {
            "read_only": True,
            "human_approval_required": True,
            "automatic_supplier_selection": False,
            "automatic_purchase_order_creation": False,
            "procurement_execution_allowed": False,
        },
    }


def build_reorder_grounded_evidence(
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Preserve the original governed evidence and append a
    deterministic reorder explanation for LLM grounding.

    This does not perform any additional I/O or mutation.
    """
    evidence = plan.get("evidence", [])

    if not isinstance(evidence, list):
        raise EvidenceExplanationError(
            "Plan evidence must be a list"
        )

    explanation = explain_reorder_recommendation(
        plan
    )

    grounded_evidence = [
        item
        for item in evidence
        if isinstance(item, dict)
    ]

    grounded_evidence.append(
        {
            "tool": (
                "deterministic_reorder_explanation"
            ),
            "read_only": True,
            "data": explanation,
        }
    )

    return grounded_evidence


def build_stockout_ranking_grounded_evidence(
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Add a deterministic probability-based ranking for
    stockout-risk signals.

    Stage7M uses an operational priority ordering that includes
    action_required and severity before probability. This helper
    creates a separate ranking specifically for questions asking
    for the highest stockout probability.
    """

    evidence = plan.get("evidence", [])

    if not isinstance(evidence, list):
        raise EvidenceExplanationError(
            "Plan evidence must be a list"
        )

    ml_payload = _tool_data(
        plan,
        "ml_signals",
    )

    items = ml_payload.get("items", [])

    if not isinstance(items, list):
        raise EvidenceExplanationError(
            "ML signal items must be a list"
        )

    stockout_items = [
        item
        for item in items
        if isinstance(item, dict)
        and item.get("model_key") == "stockout_risk"
    ]

    def probability_value(
        item: dict[str, Any],
    ) -> float:
        value = item.get("probability")

        if isinstance(value, (int, float)):
            return float(value)

        return float("-inf")

    ranked = sorted(
        stockout_items,
        key=probability_value,
        reverse=True,
    )

    ranked_items = []

    for index, item in enumerate(
        ranked,
        start=1,
    ):
        ranked_items.append(
            {
                "rank": index,
                "branch_id": item.get("branch_id"),
                "branch_code": item.get("branch_code"),
                "branch_name": item.get("branch_name"),
                "governorate": item.get("governorate"),
                "product_id": item.get("product_id"),
                "trade_name_en": item.get(
                    "trade_name_en"
                ),
                "probability": item.get(
                    "probability"
                ),
                "threshold": item.get("threshold"),
                "severity": item.get("severity"),
                "action_required": item.get(
                    "action_required"
                ),
            }
        )

    grounded_evidence = [
        item
        for item in evidence
        if isinstance(item, dict)
    ]

    grounded_evidence.append(
        {
            "tool": (
                "deterministic_stockout_probability_ranking"
            ),
            "read_only": True,
            "data": {
                "ranking_basis": "probability_desc",
                "result_count": len(ranked_items),
                "ranking_scope": (
                    "currently returned governed "
                    "stockout-risk signals"
                ),
                "items": ranked_items,
            },
        }
    )

    return grounded_evidence


def build_supplier_lead_time_grounded_evidence(
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Add deterministic supplier lead-time ranking evidence.

    The ranking is based on:
    1. avg_actual_lead_time_days DESC
    2. delayed_receipt_rate DESC
    3. supplier_code ASC

    This mirrors the governed Stage7M lead_time ordering.
    """

    evidence = plan.get("evidence", [])

    if not isinstance(evidence, list):
        raise EvidenceExplanationError(
            "Plan evidence must be a list"
        )

    supplier_payload = _tool_data(
        plan,
        "supplier_performance",
    )

    items = supplier_payload.get("items", [])

    if not isinstance(items, list):
        raise EvidenceExplanationError(
            "Supplier items must be a list"
        )

    supplier_items = [
        item
        for item in items
        if isinstance(item, dict)
    ]

    def lead_time_value(
        item: dict[str, Any],
    ) -> float:
        value = item.get(
            "avg_actual_lead_time_days"
        )

        if isinstance(value, (int, float)):
            return float(value)

        return float("-inf")

    def delay_rate_value(
        item: dict[str, Any],
    ) -> float:
        value = item.get(
            "delayed_receipt_rate"
        )

        if isinstance(value, (int, float)):
            return float(value)

        return float("-inf")

    ranked = sorted(
        supplier_items,
        key=lambda item: (
            -lead_time_value(item),
            -delay_rate_value(item),
            str(
                item.get("supplier_code") or ""
            ),
        ),
    )

    ranked_items = []

    for index, item in enumerate(
        ranked,
        start=1,
    ):
        ranked_items.append(
            {
                "rank": index,
                "supplier_id": item.get(
                    "supplier_id"
                ),
                "supplier_code": item.get(
                    "supplier_code"
                ),
                "supplier_name": item.get(
                    "supplier_name"
                ),
                "supplier_type": item.get(
                    "supplier_type"
                ),
                "service_scope": item.get(
                    "service_scope"
                ),
                "avg_actual_lead_time_days":
                    item.get(
                        "avg_actual_lead_time_days"
                    ),
                "delayed_receipt_rate":
                    item.get(
                        "delayed_receipt_rate"
                    ),
                "reliability_score":
                    item.get(
                        "reliability_score"
                    ),
                "purchase_order_count":
                    item.get(
                        "purchase_order_count"
                    ),
                "received_po_count":
                    item.get(
                        "received_po_count"
                    ),
            }
        )

    grounded_evidence = [
        item
        for item in evidence
        if isinstance(item, dict)
    ]

    grounded_evidence.append(
        {
            "tool": (
                "deterministic_supplier_lead_time_ranking"
            ),
            "read_only": True,
            "data": {
                "ranking_basis": (
                    "avg_actual_lead_time_days_desc_"
                    "then_delayed_receipt_rate_desc"
                ),
                "result_count": len(ranked_items),
                "ranking_scope": (
                    "currently returned governed "
                    "supplier-performance records"
                ),
                "items": ranked_items,
            },
        }
    )

    return grounded_evidence


def build_demand_trend_grounded_evidence(
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Build deterministic demand-trend evidence from the
    completeness-governed analytical window.
    """

    evidence = plan.get("evidence", [])

    if not isinstance(evidence, list):
        raise EvidenceExplanationError(
            "Plan evidence must be a list"
        )

    demand_payload = _tool_data(
        plan,
        "demand_trend",
    )

    items = demand_payload.get("items", [])

    if not isinstance(items, list):
        raise EvidenceExplanationError(
            "Demand items must be a list"
        )

    rows = [
        item
        for item in items
        if isinstance(item, dict)
    ]

    rows = sorted(
        rows,
        key=lambda item: str(
            item.get("business_date") or ""
        ),
    )

    analytical_state = demand_payload.get(
        "analytical_state",
        [],
    )

    analytical_as_of = None

    if isinstance(analytical_state, list):
        for item in analytical_state:
            if isinstance(item, dict):
                value = item.get(
                    "analytical_as_of_date"
                )

                if value is not None:
                    analytical_as_of = value
                    break

    requested_rows = [
        item
        for item in rows
        if isinstance(
            item.get("requested_units"),
            (int, float),
        )
    ]

    fill_rows = [
        item
        for item in rows
        if isinstance(
            item.get("fill_rate"),
            (int, float),
        )
    ]

    summary: dict[str, Any] = {
        "scope": demand_payload.get("scope"),
        "operational_data_as_of":
            demand_payload.get(
                "operational_data_as_of"
            ),
        "analytical_as_of_date":
            analytical_as_of,
        "day_count": len(rows),
    }

    if requested_rows:
        first = requested_rows[0]
        last = requested_rows[-1]

        minimum = min(
            requested_rows,
            key=lambda item: float(
                item["requested_units"]
            ),
        )

        maximum = max(
            requested_rows,
            key=lambda item: float(
                item["requested_units"]
            ),
        )

        start_value = float(
            first["requested_units"]
        )
        end_value = float(
            last["requested_units"]
        )

        summary.update(
            {
                "start_date":
                    first.get("business_date"),
                "start_requested_units":
                    first.get("requested_units"),
                "end_date":
                    last.get("business_date"),
                "end_requested_units":
                    last.get("requested_units"),
                "absolute_change_requested_units":
                    end_value - start_value,
                "percent_change_requested_units":
                    (
                        (
                            end_value - start_value
                        )
                        / start_value
                        * 100.0
                    )
                    if start_value != 0
                    else None,
                "minimum_requested_units": {
                    "business_date":
                        minimum.get("business_date"),
                    "value":
                        minimum.get(
                            "requested_units"
                        ),
                },
                "maximum_requested_units": {
                    "business_date":
                        maximum.get("business_date"),
                    "value":
                        maximum.get(
                            "requested_units"
                        ),
                },
            }
        )

    if fill_rows:
        fill_values = [
            float(item["fill_rate"])
            for item in fill_rows
        ]

        summary.update(
            {
                "minimum_fill_rate":
                    min(fill_values),
                "maximum_fill_rate":
                    max(fill_values),
                "average_fill_rate":
                    sum(fill_values)
                    / len(fill_values),
            }
        )

    grounded_evidence = [
        item
        for item in evidence
        if isinstance(item, dict)
    ]

    grounded_evidence.append(
        {
            "tool":
                "deterministic_demand_trend_summary",
            "read_only": True,
            "data": summary,
        }
    )

    return grounded_evidence


def build_critical_stockout_grounded_evidence(
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Build deterministic evidence for CRITICAL stockout signals.

    Separates:
    - model severity,
    - probability vs threshold,
    - action_required,
    - decision-case lifecycle status.
    """

    evidence = plan.get("evidence", [])

    if not isinstance(evidence, list):
        raise EvidenceExplanationError(
            "Plan evidence must be a list"
        )

    ml_payload = _tool_data(
        plan,
        "ml_signals",
    )
    cases_payload = _tool_data(
        plan,
        "decision_cases",
    )

    ml_items = ml_payload.get("items", [])
    case_items = cases_payload.get("items", [])

    if not isinstance(ml_items, list):
        ml_items = []

    if not isinstance(case_items, list):
        case_items = []

    signal = next(
        (
            item
            for item in ml_items
            if isinstance(item, dict)
            and item.get("model_key") == "stockout_risk"
            and item.get("severity") == "CRITICAL"
        ),
        {},
    )

    case = next(
        (
            item
            for item in case_items
            if isinstance(item, dict)
            and item.get("decision_type") == "STOCKOUT"
            and item.get("severity") == "CRITICAL"
        ),
        {},
    )

    # Case evidence may contain the same governed model fields.
    source = signal or case

    if not source:
        raise EvidenceExplanationError(
            "CRITICAL stockout evidence is unavailable"
        )

    probability = source.get("probability")
    threshold = source.get("threshold")

    threshold_multiple = None

    if (
        isinstance(probability, (int, float))
        and isinstance(threshold, (int, float))
        and float(threshold) > 0
    ):
        threshold_multiple = (
            float(probability)
            / float(threshold)
        )

    summary = {
        "branch_id": source.get("branch_id"),
        "branch_code": source.get("branch_code"),
        "branch_name": source.get("branch_name"),
        "product_id": source.get("product_id"),
        "trade_name_en": source.get(
            "trade_name_en"
        ),
        "scientific_name": source.get(
            "scientific_name"
        ),
        "model_key": source.get("model_key"),
        "model_version": source.get(
            "model_version"
        ),
        "severity": source.get("severity"),
        "probability": probability,
        "threshold": threshold,
        "probability_above_threshold": (
            isinstance(probability, (int, float))
            and isinstance(threshold, (int, float))
            and float(probability) > float(threshold)
        ),
        "threshold_multiple":
            threshold_multiple,
        "action_required":
            source.get("action_required"),
        "case_status":
            case.get("status"),
        "resolution_code":
            case.get("resolution_code"),
        "approval_required":
            case.get("approval_required"),
        "auto_execution_allowed":
            case.get("auto_execution_allowed"),
        "interpretation": (
            "Severity and actionability are separate governed "
            "fields. action_required=false must not be interpreted "
            "as meaning the CRITICAL model signal did not exist."
        ),
        "case_lifecycle_limitation": (
            "A CLOSED case with MODEL_CLEARED describes the "
            "decision-case lifecycle and must not be presented as "
            "retroactively invalidating the original CRITICAL "
            "model signal."
        ),
    }

    grounded_evidence = [
        item
        for item in evidence
        if isinstance(item, dict)
    ]

    grounded_evidence.append(
        {
            "tool":
                "deterministic_critical_stockout_explanation",
            "read_only": True,
            "data": summary,
        }
    )

    return grounded_evidence


def build_human_approval_grounded_evidence(
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Build deterministic human-approval workflow evidence.

    Separates:
    - decision type,
    - approval requirement,
    - current workflow status,
    - approved draft state,
    - supplier selection,
    - PO / execution permissions.
    """

    evidence = plan.get("evidence", [])

    if not isinstance(evidence, list):
        raise EvidenceExplanationError(
            "Plan evidence must be a list"
        )

    cases_payload = _tool_data(
        plan,
        "decision_cases",
    )

    items = cases_payload.get("items", [])

    if not isinstance(items, list):
        raise EvidenceExplanationError(
            "Decision case items must be a list"
        )

    case_items = [
        item
        for item in items
        if isinstance(item, dict)
    ]

    approval_items = [
        item
        for item in case_items
        if item.get("approval_required") is True
    ]

    summarized_cases = []

    for item in approval_items:
        summarized_cases.append(
            {
                "case_id": item.get("case_id"),
                "decision_type": item.get(
                    "decision_type"
                ),
                "status": item.get("status"),
                "severity": item.get("severity"),
                "action_required": item.get(
                    "action_required"
                ),
                "recommended_units": item.get(
                    "recommended_units"
                ),
                "approval_required": item.get(
                    "approval_required"
                ),
                "auto_execution_allowed": item.get(
                    "auto_execution_allowed"
                ),
                "resolution_code": item.get(
                    "resolution_code"
                ),
                "draft_status": item.get(
                    "draft_status"
                ),
                "supplier_selected": item.get(
                    "supplier_selected"
                ),
                "automatic_po_allowed": item.get(
                    "automatic_po_allowed"
                ),
                "approved_by": item.get(
                    "approved_by"
                ),
                "approved_at": item.get(
                    "approved_at"
                ),
            }
        )

    decision_types = sorted(
        {
            str(item.get("decision_type"))
            for item in approval_items
            if item.get("decision_type")
        }
    )

    summary = {
        "returned_case_count": len(case_items),
        "approval_required_case_count":
            len(approval_items),
        "decision_types_requiring_approval":
            decision_types,
        "cases": summarized_cases,
        "assistant_can_approve": False,
        "assistant_can_select_supplier": False,
        "assistant_can_create_purchase_order": False,
        "assistant_can_execute_procurement": False,
        "interpretation": (
            "approval_required describes the governed "
            "workflow requirement. A status such as "
            "APPROVED_DRAFT means a human-approved draft "
            "exists; it does not mean a purchase order was "
            "automatically created or executed."
        ),
    }

    grounded_evidence = [
        item
        for item in evidence
        if isinstance(item, dict)
    ]

    grounded_evidence.append(
        {
            "tool":
                "deterministic_human_approval_summary",
            "read_only": True,
            "data": summary,
        }
    )

    return grounded_evidence


def build_approved_drafts_grounded_evidence(
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Build deterministic evidence for approved replenishment drafts.

    APPROVED_DRAFT is a governed human-approved draft state.
    It must not be interpreted as supplier selection,
    purchase-order creation, or procurement execution.
    """

    evidence = plan.get("evidence", [])

    if not isinstance(evidence, list):
        raise EvidenceExplanationError(
            "Plan evidence must be a list"
        )

    cases_payload = _tool_data(
        plan,
        "decision_cases",
    )

    items = cases_payload.get("items", [])

    if not isinstance(items, list):
        raise EvidenceExplanationError(
            "Decision case items must be a list"
        )

    approved_drafts = []

    for item in items:
        if not isinstance(item, dict):
            continue

        if item.get("decision_type") != "REORDER":
            continue

        if item.get("status") != "APPROVED_DRAFT":
            continue

        approved_drafts.append(
            {
                "case_id": item.get("case_id"),
                "branch_id": item.get("branch_id"),
                "branch_code": item.get("branch_code"),
                "branch_name": item.get("branch_name"),
                "product_id": item.get("product_id"),
                "trade_name_en": item.get(
                    "trade_name_en"
                ),
                "scientific_name": item.get(
                    "scientific_name"
                ),
                "severity": item.get("severity"),
                "recommended_units": item.get(
                    "recommended_units"
                ),
                "approval_required": item.get(
                    "approval_required"
                ),
                "draft_id": item.get("draft_id"),
                "draft_status": item.get(
                    "draft_status"
                ),
                "approved_by": item.get(
                    "approved_by"
                ),
                "approved_at": item.get(
                    "approved_at"
                ),
                "supplier_selected": item.get(
                    "supplier_selected"
                ),
                "automatic_po_allowed": item.get(
                    "automatic_po_allowed"
                ),
                "auto_execution_allowed": item.get(
                    "auto_execution_allowed"
                ),
            }
        )

    summary = {
        "returned_approved_draft_count":
            len(approved_drafts),
        "approved_drafts":
            approved_drafts,
        "approved_draft_means_purchase_order":
            False,
        "assistant_can_select_supplier":
            False,
        "assistant_can_create_purchase_order":
            False,
        "assistant_can_execute_procurement":
            False,
        "interpretation": (
            "APPROVED_DRAFT means a governed "
            "human-approved replenishment draft exists. "
            "It does not establish supplier selection, "
            "purchase-order creation, or procurement "
            "execution."
        ),
    }

    grounded_evidence = [
        item
        for item in evidence
        if isinstance(item, dict)
    ]

    grounded_evidence.append(
        {
            "tool":
                "deterministic_approved_drafts_summary",
            "read_only": True,
            "data": summary,
        }
    )

    return grounded_evidence

