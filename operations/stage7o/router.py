"""Deterministic intent routing for Stage 7O.

The router decides which governed read-only tools may execute.

It does not:
- call an LLM,
- access PostgreSQL,
- execute tools,
- mutate operational state,
- select suppliers,
- create purchase orders.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from .orchestrator import PlannedToolCall


class AssistantRoutingError(RuntimeError):
    """Raised when a question cannot be routed safely."""


class AssistantIntent(StrEnum):
    HIGHEST_STOCKOUT_RISK = "HIGHEST_STOCKOUT_RISK"
    REORDER_EXPLANATION = "REORDER_EXPLANATION"
    APPROVED_REPLENISHMENT_DRAFTS = (
        "APPROVED_REPLENISHMENT_DRAFTS"
    )
    WORST_SUPPLIER_LEAD_TIME = "WORST_SUPPLIER_LEAD_TIME"
    DEMAND_CHANGE = "DEMAND_CHANGE"
    CRITICAL_STOCKOUT_SIGNAL = "CRITICAL_STOCKOUT_SIGNAL"
    HUMAN_APPROVAL_ACTIONS = "HUMAN_APPROVAL_ACTIONS"


@dataclass(frozen=True, slots=True)
class AssistantRoute:
    intent: AssistantIntent
    calls: list[PlannedToolCall]


_DEFAULT_LIST_LIMIT: Final[int] = 25


def _normalize_question(question: str) -> str:
    normalized = " ".join(
        question.strip().lower().split()
    )

    if not normalized:
        raise AssistantRoutingError(
            "Assistant question must not be blank"
        )

    return normalized


def _scope(
    *,
    branch_id: str | None,
    product_id: str | None,
) -> dict[str, str]:
    result: dict[str, str] = {}

    if branch_id is not None:
        value = branch_id.strip()

        if value:
            result["branch_id"] = value

    if product_id is not None:
        value = product_id.strip()

        if value:
            result["product_id"] = value

    return result


def _requires_pair_scope(
    *,
    branch_id: str | None,
    product_id: str | None,
) -> dict[str, str]:
    scope = _scope(
        branch_id=branch_id,
        product_id=product_id,
    )

    if (
        "branch_id" not in scope
        or "product_id" not in scope
    ):
        raise AssistantRoutingError(
            "Reorder explanation requires both "
            "branch_id and product_id"
        )

    return scope


def route_question(
    question: str,
    *,
    branch_id: str | None = None,
    product_id: str | None = None,
) -> AssistantRoute:
    """
    Map a supported natural-language intent to an allowlisted,
    read-only execution plan.

    Unknown questions fail closed.
    """

    text = _normalize_question(question)

    # ---------------------------------------------------------
    # 1. Exact reorder recommendation explanation.
    # Keep this before broader stock/reorder patterns.
    # ---------------------------------------------------------
    if (
        re.search(
            r"\bwhy\b.*\b(recommend|recommended|recommendation)\b",
            text,
        )
        or re.search(
            r"\bexplain\b.*\b(recommend|recommendation)\b",
            text,
        )
        or re.search(
            r"\bwhy\b.*\bunits?\b",
            text,
        )
    ):
        scope = _requires_pair_scope(
            branch_id=branch_id,
            product_id=product_id,
        )

        return AssistantRoute(
            intent=AssistantIntent.REORDER_EXPLANATION,
            calls=[
                PlannedToolCall(
                    tool_name="inventory_context",
                    arguments={
                        **scope,
                        "limit": 5,
                    },
                ),
                PlannedToolCall(
                    tool_name="ml_signals",
                    arguments={
                        **scope,
                        "limit": 10,
                    },
                ),
                PlannedToolCall(
                    tool_name="decision_cases",
                    arguments={
                        **scope,
                        "limit": 10,
                    },
                ),
            ],
        )

    # ---------------------------------------------------------
    # 2. Approved replenishment drafts.
    # ---------------------------------------------------------
    if (
        "approved" in text
        and (
            "draft" in text
            or "replenishment" in text
            or "reorder" in text
        )
    ):
        return AssistantRoute(
            intent=(
                AssistantIntent.APPROVED_REPLENISHMENT_DRAFTS
            ),
            calls=[
                PlannedToolCall(
                    tool_name="decision_cases",
                    arguments={
                        "status": "APPROVED_DRAFT",
                        "decision_type": "REORDER",
                        "limit": _DEFAULT_LIST_LIMIT,
                    },
                )
            ],
        )

    # ---------------------------------------------------------
    # 3. Critical stockout signal explanation/list.
    # More specific than general stockout-risk ranking.
    # ---------------------------------------------------------
    if (
        "critical" in text
        and "stockout" in text
    ):
        scope = _scope(
            branch_id=branch_id,
            product_id=product_id,
        )

        return AssistantRoute(
            intent=AssistantIntent.CRITICAL_STOCKOUT_SIGNAL,
            calls=[
                PlannedToolCall(
                    tool_name="ml_signals",
                    arguments={
                        **scope,
                        "model_key": "stockout_risk",
                        "severity": "CRITICAL",
                        "limit": _DEFAULT_LIST_LIMIT,
                    },
                ),
                PlannedToolCall(
                    tool_name="decision_cases",
                    arguments={
                        **scope,
                        "decision_type": "STOCKOUT",
                        "severity": "CRITICAL",
                        "limit": _DEFAULT_LIST_LIMIT,
                    },
                ),
            ],
        )

    # ---------------------------------------------------------
    # 4. Highest stockout-risk branches/signals.
    # Ranking correctness will remain governed by returned
    # Stage7M evidence; the router itself does not invent order.
    # ---------------------------------------------------------
    if (
        "stockout" in text
        and "risk" in text
        and (
            "highest" in text
            or "top" in text
            or "riskiest" in text
        )
    ):
        return AssistantRoute(
            intent=AssistantIntent.HIGHEST_STOCKOUT_RISK,
            calls=[
                PlannedToolCall(
                    tool_name="ml_signals",
                    arguments={
                        "model_key": "stockout_risk",
                        "limit": _DEFAULT_LIST_LIMIT,
                    },
                )
            ],
        )

    # ---------------------------------------------------------
    # 5. Supplier lead-time performance.
    # Read-only analytics only; never supplier selection.
    # ---------------------------------------------------------
    if (
        "supplier" in text
        and (
            "lead time" in text
            or "lead-time" in text
            or "leadtime" in text
        )
    ):
        return AssistantRoute(
            intent=AssistantIntent.WORST_SUPPLIER_LEAD_TIME,
            calls=[
                PlannedToolCall(
                    tool_name="supplier_performance",
                    arguments={
                        "metric": "lead_time",
                        "limit": _DEFAULT_LIST_LIMIT,
                    },
                )
            ],
        )

    # ---------------------------------------------------------
    # 6. Demand change/trend.
    # ---------------------------------------------------------
    if (
        "demand" in text
        and (
            "change" in text
            or "changed" in text
            or "trend" in text
            or "movement" in text
        )
    ):
        scope = _scope(
            branch_id=branch_id,
            product_id=None,
        )

        return AssistantRoute(
            intent=AssistantIntent.DEMAND_CHANGE,
            calls=[
                PlannedToolCall(
                    tool_name="demand_trend",
                    arguments={
                        **scope,
                        "days": 14,
                    },
                )
            ],
        )

    # ---------------------------------------------------------
    # 7. Human-approval workflow questions.
    # ---------------------------------------------------------
    if (
        "human approval" in text
        or "require approval" in text
        or "requires approval" in text
        or "need approval" in text
    ):
        return AssistantRoute(
            intent=AssistantIntent.HUMAN_APPROVAL_ACTIONS,
            calls=[
                PlannedToolCall(
                    tool_name="decision_cases",
                    arguments={
                        "limit": _DEFAULT_LIST_LIMIT,
                    },
                )
            ],
        )

    raise AssistantRoutingError(
        "UNKNOWN_INTENT: question is outside the "
        "allowlisted Stage 7O assistant intents"
    )
