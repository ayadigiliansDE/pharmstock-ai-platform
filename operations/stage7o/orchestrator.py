"""Provider-independent governed orchestration for Stage 7O."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from .client import Stage7MClient
from .tools import TOOLS, execute_tool
from operations.stage7o.provenance import build_data_context


MAX_TOOL_CALLS_PER_REQUEST: Final[int] = 5
MAX_QUESTION_LENGTH: Final[int] = 2000

_ALLOWED_SCALAR_TYPES: Final[tuple[type, ...]] = (
    str,
    int,
    float,
    bool,
)


class AssistantOrchestrationError(RuntimeError):
    """Raised when an assistant plan violates the Stage 7O contract."""


@dataclass(frozen=True, slots=True)
class PlannedToolCall:
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)


def _validate_question(question: str) -> str:
    normalized = question.strip()

    if not normalized:
        raise AssistantOrchestrationError(
            "Assistant question must not be blank"
        )

    if len(normalized) > MAX_QUESTION_LENGTH:
        raise AssistantOrchestrationError(
            "Assistant question exceeds maximum length"
        )

    return normalized


def _validate_arguments(
    arguments: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise AssistantOrchestrationError(
            "Tool arguments must be an object"
        )

    validated: dict[str, Any] = {}

    for key, value in arguments.items():
        if not isinstance(key, str):
            raise AssistantOrchestrationError(
                "Tool argument names must be strings"
            )

        if value is None:
            continue

        if not isinstance(value, _ALLOWED_SCALAR_TYPES):
            raise AssistantOrchestrationError(
                "Tool arguments must contain scalar values only"
            )

        validated[key] = value

    return validated


def validate_plan(
    calls: list[PlannedToolCall],
) -> list[PlannedToolCall]:
    if not calls:
        raise AssistantOrchestrationError(
            "Assistant plan must contain at least one tool call"
        )

    if len(calls) > MAX_TOOL_CALLS_PER_REQUEST:
        raise AssistantOrchestrationError(
            "Assistant plan exceeds maximum tool-call count"
        )

    validated: list[PlannedToolCall] = []

    for call in calls:
        tool_name = call.tool_name.strip()

        if tool_name not in TOOLS:
            raise AssistantOrchestrationError(
                f"Assistant tool is not allowlisted: {tool_name}"
            )

        validated.append(
            PlannedToolCall(
                tool_name=tool_name,
                arguments=_validate_arguments(call.arguments),
            )
        )

    return validated


async def execute_plan(
    client: Stage7MClient,
    *,
    question: str,
    calls: list[PlannedToolCall],
) -> dict[str, Any]:
    normalized_question = _validate_question(question)
    validated_calls = validate_plan(calls)

    evidence: list[dict[str, Any]] = []

    for index, call in enumerate(validated_calls, start=1):
        try:
            result = await execute_tool(
                client,
                tool_name=call.tool_name,
                arguments=call.arguments,
            )
        except Exception as exc:
            raise AssistantOrchestrationError(
                f"Governed tool execution failed: {call.tool_name}"
            ) from exc

        evidence.append(
            {
                "sequence": index,
                "tool": call.tool_name,
                "arguments": call.arguments,
                "read_only": True,
                "data": result["result"],
            }
        )

    return {
        "question": normalized_question,
        "tool_call_count": len(evidence),
        "evidence": evidence,
        "data_context": build_data_context(evidence),
        "read_only": True,
        "governance": {
            "direct_database_access": False,
            "assistant_mutations_allowed": False,
            "automatic_supplier_selection": False,
            "automatic_purchase_order_creation": False,
            "procurement_execution_allowed": False,
        },
    }
