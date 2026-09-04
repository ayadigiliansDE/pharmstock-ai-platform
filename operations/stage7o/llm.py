"""Provider-neutral LLM contract for Stage 7O.

The provider is an answer-generation boundary only.

It cannot:
- access PostgreSQL directly,
- execute Stage7M tools,
- mutate operational state,
- select suppliers,
- create purchase orders,
- override provenance or governance controls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class LLMProviderError(RuntimeError):
    """Raised when the governed LLM boundary cannot be used safely."""


@dataclass(frozen=True)
class GroundedLLMRequest:
    question: str
    evidence: list[dict[str, Any]]
    data_context: dict[str, Any]
    governance: dict[str, Any]


@dataclass(frozen=True)
class LLMAnswer:
    text: str
    provider: str
    model: str | None = None


class LLMProvider(Protocol):
    """Minimal provider-neutral generation interface."""

    name: str

    async def generate(
        self,
        request: GroundedLLMRequest,
    ) -> LLMAnswer:
        ...


_MUTATION_GOVERNANCE_KEYS = (
    "direct_database_access",
    "assistant_mutations_allowed",
    "automatic_supplier_selection",
    "automatic_purchase_order_creation",
    "procurement_execution_allowed",
)


def validate_grounded_request(
    request: GroundedLLMRequest,
) -> None:
    question = request.question.strip()

    if not question:
        raise LLMProviderError(
            "Grounded LLM question must not be blank"
        )

    if not isinstance(request.evidence, list):
        raise LLMProviderError(
            "Grounded LLM evidence must be a list"
        )

    for item in request.evidence:
        if not isinstance(item, dict):
            raise LLMProviderError(
                "Grounded LLM evidence items must be objects"
            )

        if item.get("read_only") is not True:
            raise LLMProviderError(
                "LLM evidence must come from read-only tool execution"
            )

    if not isinstance(request.data_context, dict):
        raise LLMProviderError(
            "Grounded LLM data_context must be an object"
        )

    if not isinstance(request.governance, dict):
        raise LLMProviderError(
            "Grounded LLM governance must be an object"
        )

    for key in _MUTATION_GOVERNANCE_KEYS:
        if request.governance.get(key) is not False:
            raise LLMProviderError(
                f"Unsafe LLM governance state: {key}"
            )

    contains_synthetic = request.data_context.get(
        "contains_synthetic_operational_data"
    )

    safe_live = request.data_context.get(
        "safe_to_describe_as_live_operational"
    )

    disclosure_required = request.data_context.get(
        "assistant_disclosure_required"
    )

    disclosure = request.data_context.get("disclosure")

    if contains_synthetic is True:
        if safe_live is not False:
            raise LLMProviderError(
                "Synthetic operational evidence cannot be "
                "classified as safe to describe as live"
            )

        if disclosure_required is not True:
            raise LLMProviderError(
                "Synthetic operational evidence requires disclosure"
            )

        if not isinstance(disclosure, str) or not disclosure.strip():
            raise LLMProviderError(
                "Required synthetic-data disclosure is missing"
            )

    if safe_live is True and contains_synthetic is True:
        raise LLMProviderError(
            "Contradictory operational provenance state"
        )


def build_provider_payload(
    request: GroundedLLMRequest,
) -> dict[str, Any]:
    """Build the only payload an external LLM provider may receive."""

    validate_grounded_request(request)

    policy = [
        (
            "Answer only from the supplied governed evidence. "
            "Do not invent operational facts."
        ),
        (
            "Treat data_context as authoritative provenance metadata."
        ),
        (
            "Never describe synthetic or calibrated operational "
            "evidence as live or real pharmacy operations."
        ),
        (
            "When assistant_disclosure_required is true, the final "
            "answer must clearly disclose the supplied data context."
        ),
        (
            "Do not claim a causal explanation for a model output "
            "unless the supplied evidence explicitly supports it."
        ),
        (
            "Do not execute actions, select suppliers, create purchase "
            "orders, or imply that such actions were performed."
        ),
        (
            "When evidence is insufficient, explicitly state the "
            "limitation instead of guessing."
        ),
    ]

    return {
        "policy": policy,
        "question": request.question.strip(),
        "data_context": request.data_context,
        "governance": request.governance,
        "evidence": request.evidence,
    }


class NotConfiguredLLMProvider:
    """Safe default provider used until an external provider is configured."""

    name = "NOT_CONFIGURED"

    async def generate(
        self,
        request: GroundedLLMRequest,
    ) -> LLMAnswer:
        validate_grounded_request(request)

        raise LLMProviderError(
            "LLM provider is not configured"
        )


def _deterministic_reorder_explanation(
    request: GroundedLLMRequest,
) -> dict[str, Any]:
    for item in request.evidence:
        if not isinstance(item, dict):
            continue

        if (
            item.get("tool")
            != "deterministic_reorder_explanation"
        ):
            continue

        data = item.get("data")

        if isinstance(data, dict):
            return data

    return {}


def _fact_map(
    explanation: dict[str, Any],
) -> dict[str, Any]:
    facts = explanation.get("facts", [])

    if not isinstance(facts, list):
        return {}

    result: dict[str, Any] = {}

    for item in facts:
        if not isinstance(item, dict):
            continue

        key = item.get("fact")

        if isinstance(key, str) and key:
            result[key] = item.get("value")

    return result


def _format_units(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)

    return f"{value} units"


def finalize_grounded_answer(
    request: GroundedLLMRequest,
    generated_text: str,
) -> str:
    """
    Apply deterministic safety constraints after provider generation.

    For reorder explanations where the exact quantity is not
    explainable from governed evidence, the provider's free-form
    causal narrative is replaced with a canonical evidence-grounded
    answer. This prevents unsupported causal attribution.

    Synthetic-data disclosure is emitted exactly once.
    """

    validate_grounded_request(request)

    if not isinstance(generated_text, str):
        raise LLMProviderError(
            "Generated LLM answer must be text"
        )

    generated_text = generated_text.strip()

    if not generated_text:
        raise LLMProviderError(
            "Generated LLM answer must not be blank"
        )

    explanation = _deterministic_reorder_explanation(
        request
    )

    disclosure_required = (
        request.data_context.get(
            "assistant_disclosure_required"
        )
        is True
    )

    disclosure = request.data_context.get(
        "disclosure"
    )

    if (
        explanation
        and explanation.get(
            "exact_quantity_explainable"
        )
        is False
    ):
        recommended_units = explanation.get(
            "recommended_units"
        )

        facts = _fact_map(explanation)

        available_inventory = facts.get(
            "available_inventory"
        )
        reorder_point = facts.get(
            "reorder_point"
        )
        target_stock = facts.get(
            "target_stock"
        )

        statements: list[str] = []

        if (
            disclosure_required
            and isinstance(disclosure, str)
            and disclosure.strip()
        ):
            statements.append(
                disclosure.strip()
            )

        inventory_parts: list[str] = []

        if available_inventory is not None:
            inventory_parts.append(
                "available inventory is "
                + _format_units(
                    available_inventory
                )
            )

        if reorder_point is not None:
            inventory_parts.append(
                "the reorder point is "
                + _format_units(
                    reorder_point
                )
            )

        if target_stock is not None:
            inventory_parts.append(
                "the target-stock value is "
                + _format_units(
                    target_stock
                )
            )

        if inventory_parts:
            statements.append(
                "Current inventory conditions support "
                "a replenishment need: "
                + ", ".join(inventory_parts)
                + "."
            )
        else:
            statements.append(
                "The governed evidence supports a "
                "replenishment need."
            )

        if recommended_units is not None:
            statements.append(
                "The governed ML model recommended "
                + _format_units(
                    recommended_units
                )
                + "."
            )

            statements.append(
                "The exposed evidence does not contain "
                "feature attribution or a quantity formula "
                "sufficient to prove why the recommendation "
                "is exactly "
                + _format_units(
                    recommended_units
                )
                + "."
            )
        else:
            statements.append(
                "The exposed evidence does not contain "
                "feature attribution or a quantity formula "
                "sufficient to causally decompose the model "
                "recommendation."
            )

        statements.append(
            "The target-stock value must not be treated "
            "as the formula for the ML recommendation "
            "unless model evidence explicitly proves that "
            "relationship."
        )

        return "\n\n".join(statements)

    stockout_ranking: dict[str, Any] = {}

    for item in request.evidence:
        if not isinstance(item, dict):
            continue

        if (
            item.get("tool")
            != "deterministic_stockout_probability_ranking"
        ):
            continue

        data = item.get("data")

        if isinstance(data, dict):
            stockout_ranking = data
            break

    if stockout_ranking:
        ranked_items = stockout_ranking.get(
            "items",
            [],
        )

        if not isinstance(ranked_items, list):
            raise LLMProviderError(
                "Stockout ranking items must be a list"
            )

        statements: list[str] = []

        if (
            disclosure_required
            and isinstance(disclosure, str)
            and disclosure.strip()
        ):
            statements.append(
                disclosure.strip()
            )

        if not ranked_items:
            statements.append(
                "No governed stockout-risk signals were "
                "returned for the current query."
            )

            return "\n\n".join(statements)

        top = ranked_items[0]

        if not isinstance(top, dict):
            raise LLMProviderError(
                "Top stockout ranking item is invalid"
            )

        branch_name = (
            top.get("branch_name")
            or top.get("branch_code")
            or "the top returned branch"
        )

        product_name = (
            top.get("trade_name_en")
            or "the returned product"
        )

        probability = top.get("probability")
        severity = top.get("severity")

        result_count = stockout_ranking.get(
            "result_count",
            len(ranked_items),
        )

        statement = (
            f"Among the {result_count} currently returned "
            "governed stockout-risk signal"
            f"{'' if result_count == 1 else 's'}, "
            f"{branch_name} has the highest returned "
            f"stockout probability for {product_name}"
        )

        if isinstance(probability, (int, float)):
            statement += (
                f" ({float(probability):.6f})"
            )

        if isinstance(severity, str) and severity:
            statement += (
                f", with severity {severity}"
            )

        statement += "."

        statements.append(statement)

        statements.append(
            "This ranking is limited to the signals returned "
            "by the current governed query and must not be "
            "described as a complete network-wide ranking "
            "unless the evidence explicitly establishes that "
            "coverage."
        )

        return "\n\n".join(statements)

    supplier_ranking: dict[str, Any] = {}

    for item in request.evidence:
        if not isinstance(item, dict):
            continue

        if (
            item.get("tool")
            != "deterministic_supplier_lead_time_ranking"
        ):
            continue

        data = item.get("data")

        if isinstance(data, dict):
            supplier_ranking = data
            break

    if supplier_ranking:
        ranked_items = supplier_ranking.get(
            "items",
            [],
        )

        if not isinstance(ranked_items, list):
            raise LLMProviderError(
                "Supplier ranking items must be a list"
            )

        statements: list[str] = []

        if (
            disclosure_required
            and isinstance(disclosure, str)
            and disclosure.strip()
        ):
            statements.append(
                disclosure.strip()
            )

        if not ranked_items:
            statements.append(
                "No governed supplier-performance "
                "records were returned for the current query."
            )

            return "\n\n".join(statements)

        top = ranked_items[0]

        if not isinstance(top, dict):
            raise LLMProviderError(
                "Top supplier ranking item is invalid"
            )

        supplier_name = (
            top.get("supplier_name")
            or top.get("supplier_code")
            or "the top returned supplier"
        )

        lead_time = top.get(
            "avg_actual_lead_time_days"
        )

        delay_rate = top.get(
            "delayed_receipt_rate"
        )

        reliability = top.get(
            "reliability_score"
        )

        result_count = supplier_ranking.get(
            "result_count",
            len(ranked_items),
        )

        statement = (
            f"Among the {result_count} currently returned "
            "governed supplier-performance record"
            f"{'' if result_count == 1 else 's'}, "
            f"{supplier_name} has the worst returned "
            "average actual lead time"
        )

        if isinstance(lead_time, (int, float)):
            statement += (
                f" at {float(lead_time):.2f} days"
            )

        statement += "."

        statements.append(statement)

        detail_parts: list[str] = []

        if isinstance(delay_rate, (int, float)):
            detail_parts.append(
                "delayed receipt rate "
                f"{float(delay_rate):.6f}"
            )

        if isinstance(reliability, (int, float)):
            detail_parts.append(
                "reliability score "
                f"{float(reliability):.6f}"
            )

        if detail_parts:
            statements.append(
                "For that returned supplier, "
                + ", ".join(detail_parts)
                + "."
            )

        statements.append(
            "This ranking is limited to the supplier "
            "records returned by the current governed query. "
            "No supplier was selected and no purchase order "
            "was created or executed."
        )

        return "\n\n".join(statements)

    demand_summary: dict[str, Any] = {}

    for item in request.evidence:
        if not isinstance(item, dict):
            continue

        if (
            item.get("tool")
            != "deterministic_demand_trend_summary"
        ):
            continue

        data = item.get("data")

        if isinstance(data, dict):
            demand_summary = data
            break

    if demand_summary:
        statements: list[str] = []

        if (
            disclosure_required
            and isinstance(disclosure, str)
            and disclosure.strip()
        ):
            statements.append(
                disclosure.strip()
            )

        analytical_as_of = demand_summary.get(
            "analytical_as_of_date"
        )

        operational_as_of = demand_summary.get(
            "operational_data_as_of"
        )

        start_date = demand_summary.get(
            "start_date"
        )
        end_date = demand_summary.get(
            "end_date"
        )

        start_units = demand_summary.get(
            "start_requested_units"
        )
        end_units = demand_summary.get(
            "end_requested_units"
        )

        absolute_change = demand_summary.get(
            "absolute_change_requested_units"
        )

        percent_change = demand_summary.get(
            "percent_change_requested_units"
        )

        minimum = demand_summary.get(
            "minimum_requested_units"
        )

        maximum = demand_summary.get(
            "maximum_requested_units"
        )

        minimum_fill = demand_summary.get(
            "minimum_fill_rate"
        )
        maximum_fill = demand_summary.get(
            "maximum_fill_rate"
        )
        average_fill = demand_summary.get(
            "average_fill_rate"
        )

        if analytical_as_of is not None:
            statements.append(
                "The completeness-governed analytical "
                f"demand window is valid through "
                f"{analytical_as_of}."
            )

        if (
            operational_as_of is not None
            and analytical_as_of is not None
            and str(operational_as_of)
            != str(analytical_as_of)
        ):
            statements.append(
                "Operational data exists through "
                f"{operational_as_of}, but dates after "
                f"{analytical_as_of} are not used for this "
                "analytical trend summary."
            )

        if (
            start_date is not None
            and end_date is not None
            and isinstance(start_units, (int, float))
            and isinstance(end_units, (int, float))
        ):
            change_text = ""

            if isinstance(
                absolute_change,
                (int, float),
            ):
                direction = (
                    "decreased"
                    if absolute_change < 0
                    else "increased"
                    if absolute_change > 0
                    else "did not change"
                )

                change_text = (
                    f" Requested units {direction} "
                    f"by {abs(float(absolute_change)):.0f} units"
                )

                if isinstance(
                    percent_change,
                    (int, float),
                ):
                    change_text += (
                        f" ({float(percent_change):.2f}%)."
                    )
                else:
                    change_text += "."

            statements.append(
                f"From {start_date} to {end_date}, "
                f"requested units moved from "
                f"{float(start_units):.0f} to "
                f"{float(end_units):.0f}."
                + change_text
            )

        if isinstance(minimum, dict):
            min_date = minimum.get(
                "business_date"
            )
            min_value = minimum.get(
                "value"
            )

            if (
                min_date is not None
                and isinstance(
                    min_value,
                    (int, float),
                )
            ):
                statements.append(
                    "The minimum requested-units value "
                    f"in the returned analytical window "
                    f"was {float(min_value):.0f} on "
                    f"{min_date}."
                )

        if isinstance(maximum, dict):
            max_date = maximum.get(
                "business_date"
            )
            max_value = maximum.get(
                "value"
            )

            if (
                max_date is not None
                and isinstance(
                    max_value,
                    (int, float),
                )
            ):
                statements.append(
                    "The maximum requested-units value "
                    f"in the returned analytical window "
                    f"was {float(max_value):.0f} on "
                    f"{max_date}."
                )

        if (
            isinstance(minimum_fill, (int, float))
            and isinstance(maximum_fill, (int, float))
        ):
            fill_statement = (
                "Fill rate ranged from "
                f"{float(minimum_fill) * 100:.2f}% "
                "to "
                f"{float(maximum_fill) * 100:.2f}%"
            )

            if isinstance(
                average_fill,
                (int, float),
            ):
                fill_statement += (
                    f", averaging "
                    f"{float(average_fill) * 100:.2f}%"
                )

            fill_statement += "."

            statements.append(
                fill_statement
            )

        statements.append(
            "This summary describes only the returned "
            "completeness-governed analytical window and "
            "does not infer causes for demand changes."
        )

        return "\n\n".join(statements)

    critical_stockout: dict[str, Any] = {}

    for item in request.evidence:
        if not isinstance(item, dict):
            continue

        if (
            item.get("tool")
            != "deterministic_critical_stockout_explanation"
        ):
            continue

        data = item.get("data")

        if isinstance(data, dict):
            critical_stockout = data
            break

    if critical_stockout:
        statements: list[str] = []

        if (
            disclosure_required
            and isinstance(disclosure, str)
            and disclosure.strip()
        ):
            statements.append(
                disclosure.strip()
            )

        branch_name = (
            critical_stockout.get("branch_name")
            or critical_stockout.get("branch_code")
            or "the returned branch"
        )

        product_name = (
            critical_stockout.get("trade_name_en")
            or "the returned product"
        )

        severity = critical_stockout.get(
            "severity"
        )
        probability = critical_stockout.get(
            "probability"
        )
        threshold = critical_stockout.get(
            "threshold"
        )
        threshold_multiple = (
            critical_stockout.get(
                "threshold_multiple"
            )
        )

        action_required = critical_stockout.get(
            "action_required"
        )

        case_status = critical_stockout.get(
            "case_status"
        )

        resolution_code = critical_stockout.get(
            "resolution_code"
        )

        approval_required = (
            critical_stockout.get(
                "approval_required"
            )
        )

        auto_execution_allowed = (
            critical_stockout.get(
                "auto_execution_allowed"
            )
        )

        statements.append(
            f"The governed stockout-risk signal for "
            f"{product_name} at {branch_name} has severity "
            f"{severity or 'UNKNOWN'}."
        )

        if (
            isinstance(probability, (int, float))
            and isinstance(threshold, (int, float))
        ):
            statement = (
                "The model probability is "
                f"{float(probability):.12f} "
                f"({float(probability) * 100:.2f}%), "
                "compared with a governed threshold of "
                f"{float(threshold):.12f} "
                f"({float(threshold) * 100:.2f}%)."
            )

            statements.append(statement)

        if isinstance(
            threshold_multiple,
            (int, float),
        ):
            statements.append(
                "The returned probability is approximately "
                f"{float(threshold_multiple):.2f} times "
                "the governed threshold."
            )

        if action_required is False:
            statements.append(
                "action_required is false. This is a "
                "separate governed actionability field and "
                "does not mean the CRITICAL model signal "
                "did not exist."
            )
        elif action_required is True:
            statements.append(
                "action_required is true for this returned "
                "signal."
            )

        if (
            case_status is not None
            or resolution_code is not None
        ):
            lifecycle = (
                "The associated decision case"
            )

            if case_status is not None:
                lifecycle += (
                    f" is {case_status}"
                )

            if resolution_code is not None:
                lifecycle += (
                    f" with resolution code "
                    f"{resolution_code}"
                )

            lifecycle += (
                ". This describes the decision-case "
                "lifecycle and must not be interpreted as "
                "retroactively invalidating the original "
                "model signal."
            )

            statements.append(lifecycle)

        if approval_required is True:
            statements.append(
                "Human approval remains required for "
                "governed decision workflow actions."
            )

        if auto_execution_allowed is False:
            statements.append(
                "Automatic execution is not allowed."
            )

        statements.append(
            "The exposed evidence supports the signal "
            "classification and lifecycle fields above, "
            "but does not provide a causal explanation "
            "for why the model produced this probability."
        )

        return "\n\n".join(statements)

    approved_drafts_summary: dict[str, Any] = {}

    for item in request.evidence:
        if not isinstance(item, dict):
            continue

        if (
            item.get("tool")
            != "deterministic_approved_drafts_summary"
        ):
            continue

        data = item.get("data")

        if isinstance(data, dict):
            approved_drafts_summary = data
            break

    if approved_drafts_summary:
        statements: list[str] = []

        if (
            disclosure_required
            and isinstance(disclosure, str)
            and disclosure.strip()
        ):
            statements.append(
                disclosure.strip()
            )

        drafts = approved_drafts_summary.get(
            "approved_drafts",
            [],
        )

        count = approved_drafts_summary.get(
            "returned_approved_draft_count",
            0,
        )

        statements.append(
            f"The governed query returned {count} "
            "approved replenishment draft"
            + ("" if count == 1 else "s")
            + "."
        )

        if isinstance(drafts, list):
            for draft in drafts:
                if not isinstance(draft, dict):
                    continue

                branch = (
                    draft.get("branch_code")
                    or draft.get("branch_name")
                    or draft.get("branch_id")
                    or "unknown branch"
                )

                product = (
                    draft.get("trade_name_en")
                    or draft.get("product_id")
                    or "unknown product"
                )

                units = draft.get(
                    "recommended_units"
                )

                severity = draft.get(
                    "severity"
                )

                approved_by = draft.get(
                    "approved_by"
                )

                text = (
                    f"{branch} ? {product}"
                )

                if isinstance(units, (int, float)):
                    text += (
                        f": {float(units):.0f} units"
                    )

                if severity:
                    text += (
                        f", severity {severity}"
                    )

                if approved_by:
                    text += (
                        f", approved by {approved_by}"
                    )

                text += "."

                statements.append(text)

        statements.append(
            "APPROVED_DRAFT means a governed "
            "human-approved replenishment draft exists."
        )

        statements.append(
            "It does not establish supplier selection, "
            "purchase-order creation, or procurement "
            "execution."
        )

        statements.append(
            "The assistant cannot select suppliers, "
            "create purchase orders, or execute procurement."
        )

        return "\n\n".join(statements)

    human_approval: dict[str, Any] = {}

    for item in request.evidence:
        if not isinstance(item, dict):
            continue

        if (
            item.get("tool")
            != "deterministic_human_approval_summary"
        ):
            continue

        data = item.get("data")

        if isinstance(data, dict):
            human_approval = data
            break

    if human_approval:
        statements: list[str] = []

        if (
            disclosure_required
            and isinstance(disclosure, str)
            and disclosure.strip()
        ):
            statements.append(
                disclosure.strip()
            )

        decision_types = human_approval.get(
            "decision_types_requiring_approval",
            [],
        )

        if isinstance(decision_types, list) and decision_types:
            statements.append(
                "The returned governed decision types that "
                "require human approval are: "
                + ", ".join(
                    str(item)
                    for item in decision_types
                )
                + "."
            )
        else:
            statements.append(
                "No returned decision cases requiring "
                "human approval were found."
            )

        cases = human_approval.get(
            "cases",
            [],
        )

        if isinstance(cases, list):
            for case in cases:
                if not isinstance(case, dict):
                    continue

                decision_type = case.get(
                    "decision_type"
                )
                status = case.get("status")
                approval_required = case.get(
                    "approval_required"
                )

                parts = []

                if decision_type is not None:
                    parts.append(
                        f"type {decision_type}"
                    )

                if status is not None:
                    parts.append(
                        f"status {status}"
                    )

                if approval_required is True:
                    parts.append(
                        "approval_required=true"
                    )

                if parts:
                    statements.append(
                        "Returned case: "
                        + ", ".join(parts)
                        + "."
                    )

                if (
                    decision_type == "REORDER"
                    and status == "APPROVED_DRAFT"
                ):
                    recommended_units = case.get(
                        "recommended_units"
                    )

                    draft_text = (
                        "The REORDER case is an "
                        "APPROVED_DRAFT"
                    )

                    if isinstance(
                        recommended_units,
                        (int, float),
                    ):
                        draft_text += (
                            f" for "
                            f"{float(recommended_units):.0f} units"
                        )

                    draft_text += (
                        ". This means a human-approved draft "
                        "exists; it does not mean a purchase "
                        "order was automatically created or "
                        "executed."
                    )

                    statements.append(
                        draft_text
                    )

        statements.append(
            "The assistant cannot approve decision cases."
        )

        statements.append(
            "The assistant cannot select suppliers."
        )

        statements.append(
            "The assistant cannot create purchase orders."
        )

        statements.append(
            "The assistant cannot execute procurement."
        )

        statements.append(
            "Sensitive workflow actions remain under "
            "human control."
        )

        return "\n\n".join(statements)

    # For other grounded-answer types, keep provider output but
    # normalize the required disclosure to exactly one occurrence.
    if (
        disclosure_required
        and isinstance(disclosure, str)
        and disclosure.strip()
    ):
        disclosure_text = disclosure.strip()

        while disclosure_text in generated_text:
            generated_text = generated_text.replace(
                disclosure_text,
                "",
            ).strip()

        if generated_text:
            return (
                disclosure_text
                + "\n\n"
                + generated_text
            )

        return disclosure_text

    return generated_text

