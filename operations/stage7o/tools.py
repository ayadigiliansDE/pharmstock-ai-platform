"""Governed read-only tool registry for the Stage 7O assistant."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Final

from .client import Stage7MClient


ToolHandler = Callable[
    [Stage7MClient, dict[str, Any]],
    Awaitable[dict[str, Any]],
]


@dataclass(frozen=True, slots=True)
class AssistantTool:
    name: str
    description: str
    handler: ToolHandler


async def _inventory_context(
    client: Stage7MClient,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    allowed = {
        "branch_id",
        "product_id",
        "below_reorder",
        "zero_stock",
        "limit",
    }
    return await client.inventory(
        {
            key: value
            for key, value in arguments.items()
            if key in allowed and value is not None
        }
    )


async def _ml_signals(
    client: Stage7MClient,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    allowed = {
        "branch_id",
        "product_id",
        "model_key",
        "severity",
        "action_required",
        "limit",
    }
    return await client.ml_signals(
        {
            key: value
            for key, value in arguments.items()
            if key in allowed and value is not None
        }
    )


async def _demand_trend(
    client: Stage7MClient,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    allowed = {
        "branch_id",
        "provenance_class",
        "days",
    }
    return await client.demand(
        {
            key: value
            for key, value in arguments.items()
            if key in allowed and value is not None
        }
    )


async def _supplier_performance(
    client: Stage7MClient,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    allowed = {
        "is_active",
        "supplier_type",
        "service_scope",
        "metric",
        "limit",
    }
    return await client.suppliers(
        {
            key: value
            for key, value in arguments.items()
            if key in allowed and value is not None
        }
    )


async def _decision_cases(
    client: Stage7MClient,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    allowed = {
        "status",
        "decision_type",
        "severity",
        "branch_id",
        "product_id",
        "limit",
    }
    return await client.cases(
        {
            key: value
            for key, value in arguments.items()
            if key in allowed and value is not None
        }
    )


TOOLS: Final[dict[str, AssistantTool]] = {
    "inventory_context": AssistantTool(
        name="inventory_context",
        description=(
            "Read governed branch-product inventory context, including "
            "available stock and reorder status."
        ),
        handler=_inventory_context,
    ),
    "ml_signals": AssistantTool(
        name="ml_signals",
        description=(
            "Read governed ML signals such as reorder recommendations "
            "and stockout-risk predictions."
        ),
        handler=_ml_signals,
    ),
    "demand_trend": AssistantTool(
        name="demand_trend",
        description=(
            "Read demand trends using the completeness-governed "
            "analytical window."
        ),
        handler=_demand_trend,
    ),
    "supplier_performance": AssistantTool(
        name="supplier_performance",
        description=(
            "Read supplier performance analytics. This tool never "
            "selects or commits a supplier."
        ),
        handler=_supplier_performance,
    ),
    "decision_cases": AssistantTool(
        name="decision_cases",
        description=(
            "Read governed operational decision cases and approved drafts."
        ),
        handler=_decision_cases,
    ),
}


def tool_catalog() -> list[dict[str, str]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
        }
        for tool in TOOLS.values()
    ]


async def execute_tool(
    client: Stage7MClient,
    *,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tool = TOOLS.get(tool_name.strip())

    if tool is None:
        raise ValueError(
            f"Assistant tool is not allowlisted: {tool_name}"
        )

    result = await tool.handler(
        client,
        arguments or {},
    )

    return {
        "tool": tool.name,
        "read_only": True,
        "result": result,
    }
