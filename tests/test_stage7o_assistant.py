from __future__ import annotations

from pathlib import Path
from contextlib import asynccontextmanager

from pharmstock.onprem.stage7o import (
    DEFAULT_PORT,
    DEFAULT_STAGE7M_BASE_URL,
    STAGE7O_VERSION,
    stage7o_contract,
)


def test_stage7o_contract_is_http_only_and_non_mutating() -> None:
    contract = stage7o_contract()

    assert STAGE7O_VERSION == "0.39.0"
    assert DEFAULT_PORT == 8092
    assert DEFAULT_STAGE7M_BASE_URL == "http://stage7m-api:8091"

    assert contract["runtime"] == "STANDALONE_AI_ASSISTANT"

    architecture = contract["architecture"]
    assert architecture["operational_data_boundary"] == "STAGE7M_HTTP_API_ONLY"
    assert architecture["direct_database_access"] is False
    assert architecture["postgres_driver_present"] is False
    assert architecture["bigquery_direct_access"] is False
    assert architecture["vector_database_required"] is False

    governance = contract["governance"]
    assert governance["human_approval_required"] is True
    assert governance["assistant_mutations_allowed"] is False
    assert governance["automatic_purchase_order_creation"] is False
    assert governance["automatic_supplier_selection"] is False
    assert governance["procurement_execution_allowed"] is False

    assert contract["upstream"]["methods"] == ["GET"]
    assert contract["cloud_mutation"] is False
    assert contract["bigquery_write"] is False


def test_stage7o_runtime_has_http_client_but_no_database_driver() -> None:
    requirements = Path(
        "infra/docker/stage7o/requirements.txt"
    ).read_text(encoding="utf-8").lower()

    assert "fastapi==0.116.1" in requirements
    assert "uvicorn[standard]==0.35.0" in requirements
    assert "httpx==0.28.1" in requirements

    forbidden = (
        "psycopg",
        "asyncpg",
        "sqlalchemy",
        "google-cloud-bigquery",
    )

    for dependency in forbidden:
        assert dependency not in requirements


def test_stage7o_docker_runtime_is_lightweight_and_reproducible() -> None:
    dockerfile = Path(
        "infra/docker/stage7o/Dockerfile"
    ).read_text(encoding="utf-8")

    assert "FROM python:3.12-slim" in dockerfile
    assert "stage7o/requirements.txt" in dockerfile
    assert "pip install --no-cache-dir" in dockerfile


def test_stage7o_client_uses_only_stage7m_http_get_boundary() -> None:
    source = Path(
        "operations/stage7o/client.py"
    ).read_text(encoding="utf-8")

    assert "httpx.AsyncClient" in source
    assert "X-PharmStock-Api-Key" in source
    assert "await self._client.get(" in source

    assert "await self._client.post(" not in source
    assert "await self._client.put(" not in source
    assert "await self._client.patch(" not in source
    assert "await self._client.delete(" not in source

    assert "/v1/assistant/inventory" in source
    assert "/v1/assistant/ml-signals" in source
    assert "/v1/assistant/demand" in source
    assert "/v1/assistant/suppliers" in source
    assert "/v1/cases" in source


def test_stage7o_service_has_no_direct_database_imports() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in Path("operations/stage7o").glob("*.py")
    )

    forbidden = (
        "import psycopg",
        "from psycopg",
        "import asyncpg",
        "from asyncpg",
        "sqlalchemy",
        "google.cloud.bigquery",
    )

    for marker in forbidden:
        assert marker not in sources


def test_stage7o_health_requires_safe_stage7m_governance() -> None:
    source = Path(
        "operations/stage7o/api.py"
    ).read_text(encoding="utf-8")

    assert '@app.get("/health")' in source
    assert 'upstream.get("status") == "HEALTHY"' in source
    assert 'upstream.get("procurement_write_blocked") is True' in source
    assert 'upstream.get("automatic_po_creation") is False' in source

    assert '"direct_database_access": False' in source
    assert '"automatic_supplier_selection": False' in source
    assert '"automatic_purchase_order_creation": False' in source


def test_stage7o_meta_exposes_runtime_contract() -> None:
    source = Path(
        "operations/stage7o/api.py"
    ).read_text(encoding="utf-8")

    assert '@app.get("/v1/meta")' in source
    assert "stage7o_contract()" in source
    assert '"stage7m_api_key_configured"' in source


def test_stage7o_llm_is_not_required_for_service_health_yet() -> None:
    contract = stage7o_contract()

    assert contract["llm"]["provider_adapter"] == "NOT_CONFIGURED"
    assert contract["llm"]["provider_required_for_health"] is False
from pathlib import Path


def test_stage7o_compose_is_loopback_only_and_calls_stage7m() -> None:
    compose = Path(
        "infra/docker/docker-compose.stage7o.yml"
    ).read_text(encoding="utf-8")

    assert "pharmstock-stage7o-assistant:0.39.0" in compose
    assert '"127.0.0.1:8092:8092"' in compose
    assert "http://stage7m-api:8091" in compose
    assert "operations.stage7o.api:app" in compose
    assert "PYTHONPATH: /workspace:/workspace/src" in compose


def test_stage7o_compose_has_no_direct_data_platform_credentials() -> None:
    compose = Path(
        "infra/docker/docker-compose.stage7o.yml"
    ).read_text(encoding="utf-8").lower()

    forbidden = (
        "pharmstock_stage7m_postgres",
        "postgres_password",
        "postgres_user",
        "postgres_host",
        "pharmstock_bq_project",
        "google_application_credentials",
        "bigquery",
    )

    for marker in forbidden:
        assert marker not in compose


def test_stage7o_compose_has_no_direct_runtime_dependencies() -> None:
    compose = Path(
        "infra/docker/docker-compose.stage7o.yml"
    ).read_text(encoding="utf-8")

    assert "depends_on:" not in compose
    assert "stage7l-workflow:" not in compose
    assert "stage7k5-online:" not in compose
    assert "postgres:" not in compose
    assert "kafka:" not in compose


def test_stage7o_compose_requires_service_key_without_repo_default() -> None:
    compose = Path(
        "infra/docker/docker-compose.stage7o.yml"
    ).read_text(encoding="utf-8")

    assert "PHARMSTOCK_STAGE7O_STAGE7M_API_KEY:" in compose
    assert (
        '"${PHARMSTOCK_STAGE7O_STAGE7M_API_KEY:-}"'
        in compose
    )

    forbidden_defaults = (
        "stage7m-local-viewer",
        "stage7m-local-operator",
        "stage7m-local-manager",
        "stage7m-local-admin",
    )

    for secret in forbidden_defaults:
        assert secret not in compose


def test_stage7o_compose_uses_existing_external_network() -> None:
    compose = Path(
        "infra/docker/docker-compose.stage7o.yml"
    ).read_text(encoding="utf-8")

    assert "external: true" in compose
    assert "name: docker_default" in compose


def test_stage7o_healthcheck_targets_only_stage7o_http() -> None:
    compose = Path(
        "infra/docker/docker-compose.stage7o.yml"
    ).read_text(encoding="utf-8")

    assert "http://127.0.0.1:8092/health" in compose
    assert "psql" not in compose.lower()
    assert "pg_isready" not in compose.lower()
import asyncio

import pytest

from operations.stage7o.tools import (
    TOOLS,
    execute_tool,
    tool_catalog,
)


class FakeStage7MClient:
    def __init__(self) -> None:
        self.calls = []

    async def inventory(self, params):
        self.calls.append(("inventory", params))
        return {"count": 1, "items": [], "read_only": True}

    async def ml_signals(self, params):
        self.calls.append(("ml_signals", params))
        return {"count": 1, "items": [], "read_only": True}

    async def demand(self, params):
        self.calls.append(("demand", params))
        return {"items": [], "read_only": True}

    async def suppliers(self, params):
        self.calls.append(("suppliers", params))
        return {"count": 1, "items": [], "read_only": True}

    async def cases(self, params):
        self.calls.append(("cases", params))
        return {"count": 1, "items": []}


def test_stage7o_tool_registry_has_fixed_read_only_allowlist() -> None:
    assert set(TOOLS) == {
        "inventory_context",
        "ml_signals",
        "demand_trend",
        "supplier_performance",
        "decision_cases",
    }

    assert {
        item["name"]
        for item in tool_catalog()
    } == set(TOOLS)


def test_stage7o_unknown_tool_is_denied_by_default() -> None:
    client = FakeStage7MClient()

    with pytest.raises(
        ValueError,
        match="Assistant tool is not allowlisted",
    ):
        asyncio.run(
            execute_tool(
                client,
                tool_name="create_purchase_order",
                arguments={},
            )
        )

    assert client.calls == []


def test_stage7o_inventory_tool_filters_unapproved_arguments() -> None:
    client = FakeStage7MClient()

    result = asyncio.run(
        execute_tool(
            client,
            tool_name="inventory_context",
            arguments={
                "branch_id": "branch-1",
                "zero_stock": True,
                "limit": 5,
                "sql": "DELETE FROM inventory.stock_batch",
                "purchase_order": True,
            },
        )
    )

    assert client.calls == [
        (
            "inventory",
            {
                "branch_id": "branch-1",
                "zero_stock": True,
                "limit": 5,
            },
        )
    ]

    assert result["tool"] == "inventory_context"
    assert result["read_only"] is True


def test_stage7o_supplier_tool_cannot_pass_execution_arguments() -> None:
    client = FakeStage7MClient()

    result = asyncio.run(
        execute_tool(
            client,
            tool_name="supplier_performance",
            arguments={
                "metric": "lead_time",
                "is_active": True,
                "limit": 10,
                "supplier_id": "should-not-pass",
                "select_supplier": True,
                "create_po": True,
            },
        )
    )

    assert client.calls == [
        (
            "suppliers",
            {
                "metric": "lead_time",
                "is_active": True,
                "limit": 10,
            },
        )
    ]

    assert result["read_only"] is True


def test_stage7o_demand_tool_passes_only_analytical_query_arguments() -> None:
    client = FakeStage7MClient()

    asyncio.run(
        execute_tool(
            client,
            tool_name="demand_trend",
            arguments={
                "branch_id": "branch-1",
                "provenance_class": "SYNTHETIC_CALIBRATED",
                "days": 14,
                "operational_override": True,
            },
        )
    )

    assert client.calls == [
        (
            "demand",
            {
                "branch_id": "branch-1",
                "provenance_class": "SYNTHETIC_CALIBRATED",
                "days": 14,
            },
        )
    ]


def test_stage7o_decision_tool_does_not_expose_actions() -> None:
    client = FakeStage7MClient()

    asyncio.run(
        execute_tool(
            client,
            tool_name="decision_cases",
            arguments={
                "status": "APPROVED_DRAFT",
                "limit": 20,
                "action": "approve-draft",
                "actor_id": "assistant",
            },
        )
    )

    assert client.calls == [
        (
            "cases",
            {
                "status": "APPROVED_DRAFT",
                "limit": 20,
            },
        )
    ]
from operations.stage7o.orchestrator import (
    MAX_QUESTION_LENGTH,
    MAX_TOOL_CALLS_PER_REQUEST,
    AssistantOrchestrationError,
    PlannedToolCall,
    execute_plan,
    validate_plan,
)


def test_stage7o_orchestrator_rejects_blank_question() -> None:
    client = FakeStage7MClient()

    with pytest.raises(
        AssistantOrchestrationError,
        match="must not be blank",
    ):
        asyncio.run(
            execute_plan(
                client,
                question="   ",
                calls=[
                    PlannedToolCall(
                        tool_name="inventory_context",
                        arguments={},
                    )
                ],
            )
        )

    assert client.calls == []


def test_stage7o_orchestrator_rejects_oversized_question() -> None:
    client = FakeStage7MClient()

    with pytest.raises(
        AssistantOrchestrationError,
        match="exceeds maximum length",
    ):
        asyncio.run(
            execute_plan(
                client,
                question="x" * (MAX_QUESTION_LENGTH + 1),
                calls=[
                    PlannedToolCall(
                        tool_name="inventory_context",
                        arguments={},
                    )
                ],
            )
        )

    assert client.calls == []


def test_stage7o_orchestrator_rejects_unknown_tool_before_execution() -> None:
    client = FakeStage7MClient()

    with pytest.raises(
        AssistantOrchestrationError,
        match="not allowlisted",
    ):
        asyncio.run(
            execute_plan(
                client,
                question="Create a purchase order",
                calls=[
                    PlannedToolCall(
                        tool_name="create_purchase_order",
                        arguments={},
                    )
                ],
            )
        )

    assert client.calls == []


def test_stage7o_orchestrator_caps_tool_calls_per_request() -> None:
    calls = [
        PlannedToolCall(
            tool_name="inventory_context",
            arguments={},
        )
        for _ in range(MAX_TOOL_CALLS_PER_REQUEST + 1)
    ]

    with pytest.raises(
        AssistantOrchestrationError,
        match="exceeds maximum tool-call count",
    ):
        validate_plan(calls)


def test_stage7o_orchestrator_rejects_nested_tool_arguments() -> None:
    client = FakeStage7MClient()

    with pytest.raises(
        AssistantOrchestrationError,
        match="scalar values only",
    ):
        asyncio.run(
            execute_plan(
                client,
                question="Check inventory",
                calls=[
                    PlannedToolCall(
                        tool_name="inventory_context",
                        arguments={
                            "branch_id": "branch-1",
                            "payload": {
                                "sql": "DELETE FROM inventory.stock_batch"
                            },
                        },
                    )
                ],
            )
        )

    assert client.calls == []


def test_stage7o_orchestrator_executes_valid_multi_tool_plan_read_only() -> None:
    client = FakeStage7MClient()

    result = asyncio.run(
        execute_plan(
            client,
            question="Why was replenishment recommended?",
            calls=[
                PlannedToolCall(
                    tool_name="inventory_context",
                    arguments={
                        "branch_id": "branch-1",
                        "product_id": "product-1",
                        "limit": 5,
                    },
                ),
                PlannedToolCall(
                    tool_name="ml_signals",
                    arguments={
                        "branch_id": "branch-1",
                        "product_id": "product-1",
                        "limit": 10,
                    },
                ),
                PlannedToolCall(
                    tool_name="decision_cases",
                    arguments={
                        "branch_id": "branch-1",
                        "product_id": "product-1",
                        "limit": 10,
                    },
                ),
            ],
        )
    )

    assert client.calls == [
        (
            "inventory",
            {
                "branch_id": "branch-1",
                "product_id": "product-1",
                "limit": 5,
            },
        ),
        (
            "ml_signals",
            {
                "branch_id": "branch-1",
                "product_id": "product-1",
                "limit": 10,
            },
        ),
        (
            "cases",
            {
                "branch_id": "branch-1",
                "product_id": "product-1",
                "limit": 10,
            },
        ),
    ]

    assert result["tool_call_count"] == 3
    assert result["read_only"] is True

    governance = result["governance"]
    assert governance["direct_database_access"] is False
    assert governance["assistant_mutations_allowed"] is False
    assert governance["automatic_supplier_selection"] is False
    assert governance["automatic_purchase_order_creation"] is False
    assert governance["procurement_execution_allowed"] is False

    assert all(
        item["read_only"] is True
        for item in result["evidence"]
    )
from operations.stage7o.explainer import (
    EvidenceExplanationError,
    explain_reorder_recommendation,
)


def _reorder_explanation_plan() -> dict:
    return {
        "question": "Why did the model recommend 65 units?",
        "read_only": True,
        "evidence": [
            {
                "tool": "inventory_context",
                "read_only": True,
                "data": {
                    "count": 1,
                    "read_only": True,
                    "items": [
                        {
                            "branch_id": "branch-1",
                            "branch_code": "GIZ-PDT-003693",
                            "branch_name": "Synthetic Pharmacy GIZ-PDT-003693",
                            "product_id": "product-1",
                            "trade_name_en": "AUGRAM 312.5 MG 10 CHEWABLE TABS.",
                            "scientific_name": "AMOXICILLIN+CLAVULANIC ACID",
                            "available_units": 0,
                            "reorder_point_units": 5,
                            "target_stock_units": 12,
                            "zero_stock": True,
                            "below_reorder": True,
                        }
                    ],
                },
            },
            {
                "tool": "ml_signals",
                "read_only": True,
                "data": {
                    "count": 2,
                    "read_only": True,
                    "items": [
                        {
                            "model_key": "reorder_recommendation",
                            "model_version": "6",
                            "prediction_value": 65.0,
                            "action_required": True,
                            "severity": "WATCH",
                        },
                        {
                            "model_key": "stockout_risk",
                            "model_version": "6",
                            "prediction_value": 1.0,
                            "probability": 0.032890885425,
                            "threshold": 0.001920516347,
                            "action_required": False,
                            "severity": "CRITICAL",
                        },
                    ],
                },
            },
            {
                "tool": "decision_cases",
                "read_only": True,
                "data": {
                    "count": 1,
                    "items": [
                        {
                            "decision_type": "REORDER",
                            "status": "APPROVED_DRAFT",
                            "recommended_units": 65,
                            "approval_required": True,
                            "supplier_selected": False,
                            "automatic_po_allowed": False,
                        }
                    ],
                },
            },
        ],
    }


def test_stage7o_reorder_explanation_is_evidence_grounded() -> None:
    result = explain_reorder_recommendation(
        _reorder_explanation_plan()
    )

    assert result["explanation_type"] == "REORDER_RECOMMENDATION"
    assert result["recommended_units"] == 65.0

    assert result["branch"]["branch_code"] == "GIZ-PDT-003693"
    assert (
        result["product"]["trade_name_en"]
        == "AUGRAM 312.5 MG 10 CHEWABLE TABS."
    )

    facts = {
        item["fact"]: item["value"]
        for item in result["facts"]
    }

    assert facts["available_inventory"] == 0
    assert facts["reorder_point"] == 5
    assert facts["target_stock"] == 12
    assert facts["zero_stock"] is True
    assert facts["below_reorder"] is True
    assert facts["reorder_action_required"] is True

    assert facts["stockout_severity"] == "CRITICAL"
    assert facts["stockout_action_required"] is False


def test_stage7o_reorder_explanation_refuses_false_exact_quantity_causality() -> None:
    result = explain_reorder_recommendation(
        _reorder_explanation_plan()
    )

    assert result["recommended_units"] == 65.0
    assert result["exact_quantity_explainable"] is False

    combined = " ".join(
        [
            result["supported_interpretation"],
            *result["limitations"],
        ]
    ).lower()

    assert "exact" in combined
    assert "model output" in combined
    assert "feature attribution" in combined
    assert "quantity formula" in combined

    # The exposed target stock is 12, but the explanation must never
    # claim that 12 mathematically produces the model output of 65.
    assert "12 = 65" not in combined
    assert "65 = 12" not in combined
    assert "target stock caused" not in combined


def test_stage7o_reorder_explanation_preserves_human_governance() -> None:
    result = explain_reorder_recommendation(
        _reorder_explanation_plan()
    )

    facts = {
        item["fact"]: item["value"]
        for item in result["facts"]
    }

    assert facts["decision_status"] == "APPROVED_DRAFT"
    assert facts["approved_draft_units"] == 65
    assert facts["approval_required"] is True
    assert facts["supplier_selected"] is False
    assert facts["automatic_po_allowed"] is False

    governance = result["governance"]

    assert governance["read_only"] is True
    assert governance["human_approval_required"] is True
    assert governance["automatic_supplier_selection"] is False
    assert governance["automatic_purchase_order_creation"] is False
    assert governance["procurement_execution_allowed"] is False


def test_stage7o_reorder_explanation_requires_reorder_model_evidence() -> None:
    plan = _reorder_explanation_plan()

    plan["evidence"][1]["data"]["items"] = [
        {
            "model_key": "stockout_risk",
            "prediction_value": 1.0,
            "severity": "CRITICAL",
        }
    ]

    with pytest.raises(
        EvidenceExplanationError,
        match="Reorder recommendation evidence is unavailable",
    ):
        explain_reorder_recommendation(plan)


def test_stage7o_provenance_gate_separates_operational_and_reference() -> None:
    from operations.stage7o.provenance import build_data_context

    evidence = [
        {
            "tool": "inventory_context",
            "data": {
                "items": [
                    {
                        "operational_provenance_class":
                            "SYNTHETIC_CALIBRATED",
                        "reference_provenance_class":
                            "PUBLIC_MARKET_EGYPT",
                    }
                ]
            },
        }
    ]

    context = build_data_context(evidence)

    assert context["operational_provenance_classes"] == [
        "SYNTHETIC_CALIBRATED"
    ]
    assert context["reference_provenance_classes"] == [
        "PUBLIC_MARKET_EGYPT"
    ]
    assert context["operational_context"] == "SYNTHETIC_OPERATIONAL"
    assert context["reference_context"] == "PUBLIC_MARKET_EGYPT"
    assert context["contains_synthetic_operational_data"] is True
    assert context["safe_to_describe_as_live_operational"] is False
    assert context["assistant_disclosure_required"] is True


def test_stage7o_provenance_gate_never_treats_public_reference_as_live() -> None:
    from operations.stage7o.provenance import build_data_context

    evidence = [
        {
            "tool": "ml_signals",
            "data": {
                "items": [
                    {
                        "operational_provenance_class":
                            "SYNTHETIC_CALIBRATED",
                        "reference_provenance_class":
                            "PUBLIC_MARKET_EGYPT",
                    }
                ]
            },
        }
    ]

    context = build_data_context(evidence)

    assert context["reference_context"] == "PUBLIC_MARKET_EGYPT"
    assert context["contains_live_operational_data"] is False
    assert context["safe_to_describe_as_live_operational"] is False


def test_stage7o_provenance_gate_accepts_explicit_live_operational_only() -> None:
    from operations.stage7o.provenance import build_data_context

    evidence = [
        {
            "tool": "inventory_context",
            "data": {
                "items": [
                    {
                        "operational_provenance_class":
                            "LIVE_OPERATIONAL",
                        "reference_provenance_class":
                            "PUBLIC_MARKET_EGYPT",
                    }
                ]
            },
        }
    ]

    context = build_data_context(evidence)

    assert context["operational_context"] == "LIVE_OPERATIONAL"
    assert context["contains_live_operational_data"] is True
    assert context["contains_synthetic_operational_data"] is False
    assert context["safe_to_describe_as_live_operational"] is True
    assert context["assistant_disclosure_required"] is False


def test_stage7o_provenance_gate_blocks_mixed_live_and_synthetic_claim() -> None:
    from operations.stage7o.provenance import build_data_context

    evidence = [
        {
            "tool": "inventory_context",
            "data": {
                "items": [
                    {
                        "operational_provenance_class":
                            "SYNTHETIC_CALIBRATED",
                    },
                    {
                        "operational_provenance_class":
                            "LIVE_OPERATIONAL",
                    },
                ]
            },
        }
    ]

    context = build_data_context(evidence)

    assert context["operational_context"] == "MIXED_OPERATIONAL"
    assert context["contains_synthetic_operational_data"] is True
    assert context["contains_live_operational_data"] is True
    assert context["safe_to_describe_as_live_operational"] is False
    assert context["assistant_disclosure_required"] is True


def test_stage7o_provenance_gate_handles_supplier_without_reference() -> None:
    from operations.stage7o.provenance import build_data_context

    evidence = [
        {
            "tool": "supplier_performance",
            "data": {
                "items": [
                    {
                        "operational_provenance_class":
                            "SYNTHETIC_CALIBRATED",
                        "reference_provenance_class": None,
                    }
                ]
            },
        }
    ]

    context = build_data_context(evidence)

    assert context["operational_context"] == "SYNTHETIC_OPERATIONAL"
    assert context["reference_context"] == "NONE"
    assert context["reference_provenance_classes"] == []


def test_stage7o_provenance_gate_supports_legacy_demand_provenance() -> None:
    from operations.stage7o.provenance import build_data_context

    evidence = [
        {
            "tool": "demand_trend",
            "data": {
                "series": [
                    {
                        "business_date": "2026-08-22",
                        "provenance_class":
                            "SYNTHETIC_CALIBRATED",
                    }
                ]
            },
        }
    ]

    context = build_data_context(evidence)

    assert context["operational_provenance_classes"] == [
        "SYNTHETIC_CALIBRATED"
    ]
    assert context["operational_context"] == "SYNTHETIC_OPERATIONAL"
    assert context["safe_to_describe_as_live_operational"] is False
    assert context["assistant_disclosure_required"] is True


def test_stage7o_execute_plan_attaches_data_context(monkeypatch) -> None:
    import asyncio

    from operations.stage7o.orchestrator import (
        PlannedToolCall,
        execute_plan,
    )

    async def fake_execute_tool(
        client,
        *,
        tool_name,
        arguments,
    ):
        return {
            "tool": tool_name,
            "read_only": True,
            "result": {
                "items": [
                    {
                        "operational_provenance_class":
                            "SYNTHETIC_CALIBRATED",
                        "reference_provenance_class":
                            "PUBLIC_MARKET_EGYPT",
                    }
                ],
                "read_only": True,
            },
        }

    monkeypatch.setattr(
        "operations.stage7o.orchestrator.execute_tool",
        fake_execute_tool,
    )

    result = asyncio.run(
        execute_plan(
            object(),
            question="Why was replenishment recommended?",
            calls=[
                PlannedToolCall(
                    tool_name="inventory_context",
                    arguments={},
                )
            ],
        )
    )

    context = result["data_context"]

    assert context["operational_context"] == (
        "SYNTHETIC_OPERATIONAL"
    )
    assert context["reference_context"] == (
        "PUBLIC_MARKET_EGYPT"
    )
    assert context[
        "contains_synthetic_operational_data"
    ] is True
    assert context[
        "safe_to_describe_as_live_operational"
    ] is False
    assert context[
        "assistant_disclosure_required"
    ] is True


def test_stage7o_execute_plan_blocks_live_claim_for_mixed_provenance(
    monkeypatch,
) -> None:
    import asyncio

    from operations.stage7o.orchestrator import (
        PlannedToolCall,
        execute_plan,
    )

    async def fake_execute_tool(
        client,
        *,
        tool_name,
        arguments,
    ):
        return {
            "tool": tool_name,
            "read_only": True,
            "result": {
                "items": [
                    {
                        "operational_provenance_class":
                            "SYNTHETIC_CALIBRATED",
                    },
                    {
                        "operational_provenance_class":
                            "LIVE_OPERATIONAL",
                    },
                ]
            },
        }

    monkeypatch.setattr(
        "operations.stage7o.orchestrator.execute_tool",
        fake_execute_tool,
    )

    result = asyncio.run(
        execute_plan(
            object(),
            question="What is happening now?",
            calls=[
                PlannedToolCall(
                    tool_name="inventory_context",
                    arguments={},
                )
            ],
        )
    )

    context = result["data_context"]

    assert context["operational_context"] == (
        "MIXED_OPERATIONAL"
    )
    assert context[
        "safe_to_describe_as_live_operational"
    ] is False
    assert context[
        "assistant_disclosure_required"
    ] is True


def test_stage7o_execute_plan_preserves_read_only_governance_with_context(
    monkeypatch,
) -> None:
    import asyncio

    from operations.stage7o.orchestrator import (
        PlannedToolCall,
        execute_plan,
    )

    async def fake_execute_tool(
        client,
        *,
        tool_name,
        arguments,
    ):
        return {
            "tool": tool_name,
            "read_only": True,
            "result": {
                "items": [
                    {
                        "operational_provenance_class":
                            "SYNTHETIC_CALIBRATED",
                    }
                ]
            },
        }

    monkeypatch.setattr(
        "operations.stage7o.orchestrator.execute_tool",
        fake_execute_tool,
    )

    result = asyncio.run(
        execute_plan(
            object(),
            question="Show approved replenishment drafts.",
            calls=[
                PlannedToolCall(
                    tool_name="decision_cases",
                    arguments={},
                )
            ],
        )
    )

    assert result["read_only"] is True
    assert result["governance"] == {
        "direct_database_access": False,
        "assistant_mutations_allowed": False,
        "automatic_supplier_selection": False,
        "automatic_purchase_order_creation": False,
        "procurement_execution_allowed": False,
    }

    assert result["data_context"][
        "safe_to_describe_as_live_operational"
    ] is False


def test_stage7o_llm_payload_is_grounded_and_provider_neutral() -> None:
    from operations.stage7o.llm import (
        GroundedLLMRequest,
        build_provider_payload,
    )

    request = GroundedLLMRequest(
        question="Why did the model recommend 65 units?",
        evidence=[
            {
                "tool": "ml_signals",
                "read_only": True,
                "data": {
                    "items": [
                        {
                            "model_key": "reorder_recommendation",
                            "prediction_value": 65.0,
                        }
                    ]
                },
            }
        ],
        data_context={
            "operational_context": "SYNTHETIC_OPERATIONAL",
            "reference_context": "PUBLIC_MARKET_EGYPT",
            "contains_synthetic_operational_data": True,
            "safe_to_describe_as_live_operational": False,
            "assistant_disclosure_required": True,
            "disclosure": (
                "Operational evidence is SYNTHETIC_CALIBRATED "
                "and must not be described as live or real "
                "pharmacy operations."
            ),
        },
        governance={
            "direct_database_access": False,
            "assistant_mutations_allowed": False,
            "automatic_supplier_selection": False,
            "automatic_purchase_order_creation": False,
            "procurement_execution_allowed": False,
        },
    )

    payload = build_provider_payload(request)

    assert payload["question"] == (
        "Why did the model recommend 65 units?"
    )
    assert payload["evidence"] == request.evidence
    assert payload["data_context"] == request.data_context
    assert payload["governance"] == request.governance

    policy = " ".join(payload["policy"]).lower()

    assert "synthetic" in policy
    assert "live" in policy
    assert "do not invent" in policy
    assert "select suppliers" in policy
    assert "purchase orders" in policy


def test_stage7o_llm_rejects_blank_question() -> None:
    import pytest

    from operations.stage7o.llm import (
        GroundedLLMRequest,
        LLMProviderError,
        validate_grounded_request,
    )

    request = GroundedLLMRequest(
        question="   ",
        evidence=[],
        data_context={},
        governance={
            "direct_database_access": False,
            "assistant_mutations_allowed": False,
            "automatic_supplier_selection": False,
            "automatic_purchase_order_creation": False,
            "procurement_execution_allowed": False,
        },
    )

    with pytest.raises(
        LLMProviderError,
        match="must not be blank",
    ):
        validate_grounded_request(request)


def test_stage7o_llm_rejects_non_read_only_evidence() -> None:
    import pytest

    from operations.stage7o.llm import (
        GroundedLLMRequest,
        LLMProviderError,
        validate_grounded_request,
    )

    request = GroundedLLMRequest(
        question="Show the case.",
        evidence=[
            {
                "tool": "decision_cases",
                "read_only": False,
                "data": {},
            }
        ],
        data_context={},
        governance={
            "direct_database_access": False,
            "assistant_mutations_allowed": False,
            "automatic_supplier_selection": False,
            "automatic_purchase_order_creation": False,
            "procurement_execution_allowed": False,
        },
    )

    with pytest.raises(
        LLMProviderError,
        match="read-only",
    ):
        validate_grounded_request(request)


def test_stage7o_llm_rejects_unsafe_governance() -> None:
    import pytest

    from operations.stage7o.llm import (
        GroundedLLMRequest,
        LLMProviderError,
        validate_grounded_request,
    )

    request = GroundedLLMRequest(
        question="Create a purchase order.",
        evidence=[],
        data_context={},
        governance={
            "direct_database_access": False,
            "assistant_mutations_allowed": False,
            "automatic_supplier_selection": False,
            "automatic_purchase_order_creation": True,
            "procurement_execution_allowed": False,
        },
    )

    with pytest.raises(
        LLMProviderError,
        match="Unsafe LLM governance state",
    ):
        validate_grounded_request(request)


def test_stage7o_llm_requires_synthetic_disclosure() -> None:
    import pytest

    from operations.stage7o.llm import (
        GroundedLLMRequest,
        LLMProviderError,
        validate_grounded_request,
    )

    request = GroundedLLMRequest(
        question="What is the stockout risk?",
        evidence=[],
        data_context={
            "contains_synthetic_operational_data": True,
            "safe_to_describe_as_live_operational": False,
            "assistant_disclosure_required": False,
            "disclosure": "",
        },
        governance={
            "direct_database_access": False,
            "assistant_mutations_allowed": False,
            "automatic_supplier_selection": False,
            "automatic_purchase_order_creation": False,
            "procurement_execution_allowed": False,
        },
    )

    with pytest.raises(
        LLMProviderError,
        match="requires disclosure",
    ):
        validate_grounded_request(request)


def test_stage7o_llm_rejects_synthetic_data_marked_live_safe() -> None:
    import pytest

    from operations.stage7o.llm import (
        GroundedLLMRequest,
        LLMProviderError,
        validate_grounded_request,
    )

    request = GroundedLLMRequest(
        question="What is happening now?",
        evidence=[],
        data_context={
            "contains_synthetic_operational_data": True,
            "safe_to_describe_as_live_operational": True,
            "assistant_disclosure_required": True,
            "disclosure": "Synthetic operational evidence.",
        },
        governance={
            "direct_database_access": False,
            "assistant_mutations_allowed": False,
            "automatic_supplier_selection": False,
            "automatic_purchase_order_creation": False,
            "procurement_execution_allowed": False,
        },
    )

    with pytest.raises(
        LLMProviderError,
        match="cannot be classified as safe",
    ):
        validate_grounded_request(request)


def test_stage7o_not_configured_llm_provider_fails_closed() -> None:
    import asyncio
    import pytest

    from operations.stage7o.llm import (
        GroundedLLMRequest,
        LLMProviderError,
        NotConfiguredLLMProvider,
    )

    request = GroundedLLMRequest(
        question="Explain this evidence.",
        evidence=[],
        data_context={
            "contains_synthetic_operational_data": True,
            "safe_to_describe_as_live_operational": False,
            "assistant_disclosure_required": True,
            "disclosure": (
                "Operational evidence is synthetic."
            ),
        },
        governance={
            "direct_database_access": False,
            "assistant_mutations_allowed": False,
            "automatic_supplier_selection": False,
            "automatic_purchase_order_creation": False,
            "procurement_execution_allowed": False,
        },
    )

    provider = NotConfiguredLLMProvider()

    with pytest.raises(
        LLMProviderError,
        match="not configured",
    ):
        asyncio.run(provider.generate(request))


def _stage7o_openai_request():
    from operations.stage7o.llm import GroundedLLMRequest

    return GroundedLLMRequest(
        question="Why did the model recommend 65 units?",
        evidence=[
            {
                "tool": "ml_signals",
                "read_only": True,
                "data": {
                    "items": [
                        {
                            "model_key": "reorder_recommendation",
                            "prediction_value": 65.0,
                            "operational_provenance_class":
                                "SYNTHETIC_CALIBRATED",
                            "reference_provenance_class":
                                "PUBLIC_MARKET_EGYPT",
                        }
                    ]
                },
            }
        ],
        data_context={
            "operational_context":
                "SYNTHETIC_OPERATIONAL",
            "reference_context":
                "PUBLIC_MARKET_EGYPT",
            "contains_synthetic_operational_data":
                True,
            "contains_live_operational_data":
                False,
            "safe_to_describe_as_live_operational":
                False,
            "assistant_disclosure_required":
                True,
            "disclosure": (
                "Operational evidence is "
                "SYNTHETIC_CALIBRATED and must not "
                "be described as live or real pharmacy "
                "operations."
            ),
        },
        governance={
            "direct_database_access": False,
            "assistant_mutations_allowed": False,
            "automatic_supplier_selection": False,
            "automatic_purchase_order_creation": False,
            "procurement_execution_allowed": False,
        },
    )


class _FakeOpenAIResponse:
    def __init__(
        self,
        *,
        status_code=200,
        payload=None,
        json_error=False,
    ):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("invalid json")

        return self._payload


class _FakeOpenAIClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def post(
        self,
        url,
        *,
        headers,
        json,
    ):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
            }
        )

        return self.response


def test_stage7o_openai_provider_uses_governed_responses_payload() -> None:
    import asyncio
    import json

    from operations.stage7o.providers.openai import (
        OpenAIResponsesProvider,
    )

    fake = _FakeOpenAIClient(
        _FakeOpenAIResponse(
            payload={
                "status": "completed",
                "model": "gpt-5.6-terra",
                "output_text":
                    "The evidence supports replenishment.",
            }
        )
    )

    provider = OpenAIResponsesProvider(
        api_key="test-key",
        model="gpt-5.6-terra",
        client=fake,
    )

    answer = asyncio.run(
        provider.generate(
            _stage7o_openai_request()
        )
    )

    assert len(fake.calls) == 1

    call = fake.calls[0]
    payload = call["json"]

    assert call["url"] == (
        "https://api.openai.com/v1/responses"
    )

    assert call["headers"]["Authorization"] == (
        "Bearer test-key"
    )

    assert payload["model"] == "gpt-5.6-terra"
    assert payload["store"] is False
    assert payload["tools"] == []
    assert payload["parallel_tool_calls"] is False
    assert payload["max_output_tokens"] == 1600
    assert payload["text"]["verbosity"] == "low"

    decoded = json.loads(payload["input"])

    assert decoded["question"] == (
        "Why did the model recommend 65 units?"
    )

    assert decoded["data_context"][
        "safe_to_describe_as_live_operational"
    ] is False

    assert decoded["governance"][
        "automatic_purchase_order_creation"
    ] is False

    assert "SYNTHETIC_CALIBRATED" in answer.text
    assert (
        "The evidence supports replenishment."
        in answer.text
    )

    assert answer.provider == "OPENAI_RESPONSES"
    assert answer.model == "gpt-5.6-terra"


def test_stage7o_openai_provider_adds_disclosure_deterministically() -> None:
    import asyncio

    from operations.stage7o.providers.openai import (
        OpenAIResponsesProvider,
    )

    fake = _FakeOpenAIClient(
        _FakeOpenAIResponse(
            payload={
                "status": "completed",
                "output_text":
                    "Recommended quantity is 65 units.",
            }
        )
    )

    provider = OpenAIResponsesProvider(
        api_key="test-key",
        client=fake,
    )

    answer = asyncio.run(
        provider.generate(
            _stage7o_openai_request()
        )
    )

    assert answer.text.startswith(
        "Operational evidence is "
        "SYNTHETIC_CALIBRATED"
    )


def test_stage7o_openai_provider_does_not_duplicate_disclosure() -> None:
    import asyncio

    from operations.stage7o.providers.openai import (
        OpenAIResponsesProvider,
    )

    disclosure = (
        "Operational evidence is "
        "SYNTHETIC_CALIBRATED and must not be "
        "described as live or real pharmacy operations."
    )

    fake = _FakeOpenAIClient(
        _FakeOpenAIResponse(
            payload={
                "status": "completed",
                "output_text": (
                    f"{disclosure}\n\n"
                    "The evidence supports replenishment."
                ),
            }
        )
    )

    provider = OpenAIResponsesProvider(
        api_key="test-key",
        client=fake,
    )

    answer = asyncio.run(
        provider.generate(
            _stage7o_openai_request()
        )
    )

    assert answer.text.count(disclosure) == 1


def test_stage7o_openai_provider_extracts_nested_output_text() -> None:
    import asyncio

    from operations.stage7o.providers.openai import (
        OpenAIResponsesProvider,
    )

    fake = _FakeOpenAIClient(
        _FakeOpenAIResponse(
            payload={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text":
                                    "Grounded nested response.",
                            }
                        ],
                    }
                ],
            }
        )
    )

    provider = OpenAIResponsesProvider(
        api_key="test-key",
        client=fake,
    )

    answer = asyncio.run(
        provider.generate(
            _stage7o_openai_request()
        )
    )

    assert "Grounded nested response." in answer.text


def test_stage7o_openai_provider_fails_closed_without_api_key(
    monkeypatch,
) -> None:
    import asyncio
    import pytest

    from operations.stage7o.llm import LLMProviderError
    from operations.stage7o.providers.openai import (
        OpenAIResponsesProvider,
    )

    monkeypatch.delenv(
        "PHARMSTOCK_STAGE7O_OPENAI_API_KEY",
        raising=False,
    )

    provider = OpenAIResponsesProvider(
        api_key=None,
    )

    with pytest.raises(
        LLMProviderError,
        match="API key is not configured",
    ):
        asyncio.run(
            provider.generate(
                _stage7o_openai_request()
            )
        )


def test_stage7o_openai_provider_fails_closed_on_http_error() -> None:
    import asyncio
    import pytest

    from operations.stage7o.llm import LLMProviderError
    from operations.stage7o.providers.openai import (
        OpenAIResponsesProvider,
    )

    fake = _FakeOpenAIClient(
        _FakeOpenAIResponse(
            status_code=401,
            payload={
                "error": {
                    "message": "unauthorized",
                }
            },
        )
    )

    provider = OpenAIResponsesProvider(
        api_key="bad-key",
        client=fake,
    )

    with pytest.raises(
        LLMProviderError,
        match="HTTP 401",
    ):
        asyncio.run(
            provider.generate(
                _stage7o_openai_request()
            )
        )


def test_stage7o_openai_provider_fails_closed_on_invalid_json() -> None:
    import asyncio
    import pytest

    from operations.stage7o.llm import LLMProviderError
    from operations.stage7o.providers.openai import (
        OpenAIResponsesProvider,
    )

    fake = _FakeOpenAIClient(
        _FakeOpenAIResponse(
            status_code=200,
            json_error=True,
        )
    )

    provider = OpenAIResponsesProvider(
        api_key="test-key",
        client=fake,
    )

    with pytest.raises(
        LLMProviderError,
        match="invalid JSON",
    ):
        asyncio.run(
            provider.generate(
                _stage7o_openai_request()
            )
        )


def test_stage7o_openai_provider_requires_no_openai_sdk() -> None:
    from pathlib import Path

    requirements = Path(
        "infra/docker/stage7o/requirements.txt"
    ).read_text(encoding="utf-8").lower()

    provider_source = Path(
        "operations/stage7o/providers/openai.py"
    ).read_text(encoding="utf-8").lower()

    assert "\nopenai" not in requirements
    assert "import openai" not in provider_source
    assert "from openai" not in provider_source

    assert "httpx" in requirements
    assert "import httpx" in provider_source


def test_stage7o_provider_factory_defaults_to_not_configured(
    monkeypatch,
) -> None:
    from operations.stage7o.llm import (
        NotConfiguredLLMProvider,
    )
    from operations.stage7o.provider_factory import (
        build_llm_provider,
        provider_runtime_metadata,
    )

    monkeypatch.delenv(
        "PHARMSTOCK_STAGE7O_LLM_PROVIDER",
        raising=False,
    )
    monkeypatch.delenv(
        "PHARMSTOCK_STAGE7O_OPENAI_API_KEY",
        raising=False,
    )
    monkeypatch.delenv(
        "PHARMSTOCK_STAGE7O_OPENAI_MODEL",
        raising=False,
    )

    provider = build_llm_provider()

    assert isinstance(
        provider,
        NotConfiguredLLMProvider,
    )

    metadata = provider_runtime_metadata(provider)

    assert metadata["configured_selection"] == "none"
    assert metadata["provider"] == "NOT_CONFIGURED"
    assert metadata["configured"] is False
    assert metadata["api_key_present"] is False


def test_stage7o_provider_factory_openai_requires_key(
    monkeypatch,
) -> None:
    import pytest

    from operations.stage7o.llm import (
        LLMProviderError,
    )
    from operations.stage7o.provider_factory import (
        build_llm_provider,
    )

    monkeypatch.setenv(
        "PHARMSTOCK_STAGE7O_LLM_PROVIDER",
        "openai",
    )
    monkeypatch.delenv(
        "PHARMSTOCK_STAGE7O_OPENAI_API_KEY",
        raising=False,
    )

    with pytest.raises(
        LLMProviderError,
        match="OpenAI API key is missing",
    ):
        build_llm_provider()


def test_stage7o_provider_factory_rejects_unknown_provider(
    monkeypatch,
) -> None:
    import pytest

    from operations.stage7o.llm import (
        LLMProviderError,
    )
    from operations.stage7o.provider_factory import (
        build_llm_provider,
    )

    monkeypatch.setenv(
        "PHARMSTOCK_STAGE7O_LLM_PROVIDER",
        "unknown-provider",
    )

    with pytest.raises(
        LLMProviderError,
        match="Unsupported Stage7O LLM provider",
    ):
        build_llm_provider()


def test_stage7o_provider_factory_builds_openai_without_request(
    monkeypatch,
) -> None:
    from operations.stage7o.provider_factory import (
        build_llm_provider,
        provider_runtime_metadata,
    )
    from operations.stage7o.providers.openai import (
        OpenAIResponsesProvider,
    )

    monkeypatch.setenv(
        "PHARMSTOCK_STAGE7O_LLM_PROVIDER",
        "openai",
    )
    monkeypatch.setenv(
        "PHARMSTOCK_STAGE7O_OPENAI_API_KEY",
        "test-secret-key",
    )
    monkeypatch.setenv(
        "PHARMSTOCK_STAGE7O_OPENAI_MODEL",
        "test-model",
    )

    provider = build_llm_provider()

    assert isinstance(
        provider,
        OpenAIResponsesProvider,
    )

    assert provider.model == "test-model"

    metadata = provider_runtime_metadata(provider)

    assert metadata["configured_selection"] == "openai"
    assert metadata["provider"] == "OPENAI_RESPONSES"
    assert metadata["model"] == "test-model"
    assert metadata["configured"] is True
    assert metadata["api_key_present"] is True

    # Metadata may reveal presence of a secret,
    # but must never reveal the secret itself.
    assert "test-secret-key" not in repr(metadata)


def test_stage7o_api_wires_llm_provider_in_lifespan() -> None:
    from pathlib import Path

    source = Path(
        "operations/stage7o/api.py"
    ).read_text(encoding="utf-8")

    assert "build_llm_provider()" in source
    assert "app.state.llm_provider" in source
    assert "provider_runtime_metadata" in source


def test_stage7o_meta_exposes_safe_llm_runtime_metadata_only() -> None:
    from operations.stage7o.llm import (
        NotConfiguredLLMProvider,
    )
    from operations.stage7o.provider_factory import (
        provider_runtime_metadata,
    )

    provider = NotConfiguredLLMProvider()

    metadata = provider_runtime_metadata(provider)

    assert metadata == {
        "configured_selection": "none",
        "provider": "NOT_CONFIGURED",
        "model": None,
        "configured": False,
        "api_key_present": False,
    }

    serialized = repr(metadata).lower()

    assert "authorization" not in serialized
    assert "bearer " not in serialized
    assert "api_key" not in serialized or (
        "api_key_present" in serialized
    )


def test_stage7o_contract_keeps_llm_optional_for_health() -> None:
    from pharmstock.onprem.stage7o import (
        stage7o_contract,
    )

    contract = stage7o_contract()

    assert contract["llm"][
        "provider_required_for_health"
    ] is False


def test_stage7o_default_runtime_provider_remains_disabled(
    monkeypatch,
) -> None:
    from operations.stage7o.llm import (
        NotConfiguredLLMProvider,
    )
    from operations.stage7o.provider_factory import (
        build_llm_provider,
    )

    monkeypatch.delenv(
        "PHARMSTOCK_STAGE7O_LLM_PROVIDER",
        raising=False,
    )
    monkeypatch.delenv(
        "PHARMSTOCK_STAGE7O_OPENAI_API_KEY",
        raising=False,
    )
    monkeypatch.delenv(
        "PHARMSTOCK_STAGE7O_OPENAI_MODEL",
        raising=False,
    )

    provider = build_llm_provider()

    assert isinstance(
        provider,
        NotConfiguredLLMProvider,
    )


def test_stage7o_compose_llm_defaults_are_safe() -> None:
    from pathlib import Path

    source = Path(
        "infra/docker/docker-compose.stage7o.yml"
    ).read_text(encoding="utf-8")

    assert (
        'PHARMSTOCK_STAGE7O_LLM_PROVIDER: '
        '"${PHARMSTOCK_STAGE7O_LLM_PROVIDER:-ollama}"'
    ) in source

    assert (
        'PHARMSTOCK_STAGE7O_OLLAMA_BASE_URL: '
        '"${PHARMSTOCK_STAGE7O_OLLAMA_BASE_URL:-http://host.docker.internal:11434}"'
    ) in source

    assert (
        'PHARMSTOCK_STAGE7O_OLLAMA_MODEL: '
        '"${PHARMSTOCK_STAGE7O_OLLAMA_MODEL:-qwen3:4b}"'
    ) in source

    assert (
        'PHARMSTOCK_STAGE7O_OPENAI_API_KEY: '
        '"${PHARMSTOCK_STAGE7O_OPENAI_API_KEY:-}"'
    ) in source

    assert (
        'PHARMSTOCK_STAGE7O_OPENAI_MODEL: '
        '"${PHARMSTOCK_STAGE7O_OPENAI_MODEL:-gpt-5.6-terra}"'
    ) in source


def test_stage7o_compose_never_hardcodes_openai_secret() -> None:
    from pathlib import Path

    source = Path(
        "infra/docker/docker-compose.stage7o.yml"
    ).read_text(encoding="utf-8")

    key_lines = [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith(
            "PHARMSTOCK_STAGE7O_OPENAI_API_KEY:"
        )
    ]

    assert len(key_lines) == 1

    assert key_lines[0] == (
        'PHARMSTOCK_STAGE7O_OPENAI_API_KEY: '
        '"${PHARMSTOCK_STAGE7O_OPENAI_API_KEY:-}"'
    )

    lower = source.lower()

    assert "sk-proj-" not in lower
    assert "sk-" not in lower


def test_stage7o_compose_preserves_assistant_security_boundary() -> None:
    from pathlib import Path

    source = Path(
        "infra/docker/docker-compose.stage7o.yml"
    ).read_text(encoding="utf-8").lower()

    # Stage7O communicates with Stage7M only.
    assert (
        "pharmstock_stage7o_stage7m_base_url: "
        "http://stage7m-api:8091"
    ) in source

    # No direct database credentials belong in Stage7O.
    forbidden = (
        "postgres_password",
        "postgres_user",
        "database_url",
        "bigquery_credentials",
        "google_application_credentials",
    )

    for value in forbidden:
        assert value not in source


class _FakeOllamaResponse:
    def __init__(
        self,
        *,
        status_code=200,
        payload=None,
        json_error=False,
    ):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("invalid json")

        return self._payload


class _FakeOllamaClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def post(
        self,
        url,
        *,
        json,
    ):
        self.calls.append(
            {
                "url": url,
                "json": json,
            }
        )

        return self.response


def _stage7o_ollama_request():
    from operations.stage7o.llm import GroundedLLMRequest

    return GroundedLLMRequest(
        question="Why did the model recommend 65 units?",
        evidence=[
            {
                "tool": "ml_signals",
                "read_only": True,
                "data": {
                    "items": [
                        {
                            "model_key":
                                "reorder_recommendation",
                            "prediction_value": 65.0,
                            "operational_provenance_class":
                                "SYNTHETIC_CALIBRATED",
                            "reference_provenance_class":
                                "PUBLIC_MARKET_EGYPT",
                        }
                    ]
                },
            }
        ],
        data_context={
            "operational_context":
                "SYNTHETIC_OPERATIONAL",
            "reference_context":
                "PUBLIC_MARKET_EGYPT",
            "contains_synthetic_operational_data":
                True,
            "contains_live_operational_data":
                False,
            "safe_to_describe_as_live_operational":
                False,
            "assistant_disclosure_required":
                True,
            "disclosure": (
                "Operational evidence is "
                "SYNTHETIC_CALIBRATED and must not "
                "be described as live or real pharmacy "
                "operations."
            ),
        },
        governance={
            "direct_database_access": False,
            "assistant_mutations_allowed": False,
            "automatic_supplier_selection": False,
            "automatic_purchase_order_creation": False,
            "procurement_execution_allowed": False,
        },
    )


def test_stage7o_ollama_provider_strips_leaked_reasoning() -> None:
    import asyncio

    from operations.stage7o.providers.ollama import (
        OllamaProvider,
    )

    fake = _FakeOllamaClient(
        _FakeOllamaResponse(
            payload={
                "model": "qwen3:4b",
                "done": True,
                "response": (
                    "Thinking about internal steps...\n"
                    "</think>\n\n"
                    "The evidence supports replenishment."
                ),
            }
        )
    )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="qwen3:4b",
        client=fake,
    )

    answer = asyncio.run(
        provider.generate(
            _stage7o_ollama_request()
        )
    )

    assert "Thinking about internal steps" not in answer.text
    assert "</think>" not in answer.text
    assert (
        "The evidence supports replenishment."
        in answer.text
    )


def test_stage7o_ollama_provider_adds_required_disclosure() -> None:
    import asyncio

    from operations.stage7o.providers.ollama import (
        OllamaProvider,
    )

    fake = _FakeOllamaClient(
        _FakeOllamaResponse(
            payload={
                "model": "qwen3:4b",
                "done": True,
                "response":
                    "The evidence supports replenishment.",
            }
        )
    )

    provider = OllamaProvider(
        base_url="http://localhost:11434",
        client=fake,
    )

    answer = asyncio.run(
        provider.generate(
            _stage7o_ollama_request()
        )
    )

    assert answer.text.startswith(
        "Operational evidence is "
        "SYNTHETIC_CALIBRATED"
    )


def test_stage7o_ollama_provider_uses_local_generate_api() -> None:
    import asyncio

    from operations.stage7o.providers.ollama import (
        OllamaProvider,
    )

    fake = _FakeOllamaClient(
        _FakeOllamaResponse(
            payload={
                "model": "qwen3:4b",
                "done": True,
                "response":
                    "Grounded final answer.",
            }
        )
    )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        client=fake,
    )

    answer = asyncio.run(
        provider.generate(
            _stage7o_ollama_request()
        )
    )

    assert len(fake.calls) == 1

    call = fake.calls[0]

    assert call["url"] == (
        "http://127.0.0.1:11434/api/generate"
    )

    payload = call["json"]

    assert payload["model"] == "qwen3:4b"
    assert payload["stream"] is False
    assert payload["think"] is False

    assert "SYNTHETIC_CALIBRATED" in payload["prompt"]
    assert "automatic_purchase_order_creation" in payload["prompt"]

    assert answer.provider == "OLLAMA_LOCAL"
    assert answer.model == "qwen3:4b"


def test_stage7o_ollama_provider_rejects_non_local_endpoint() -> None:
    import pytest

    from operations.stage7o.llm import (
        LLMProviderError,
    )
    from operations.stage7o.providers.ollama import (
        OllamaProvider,
    )

    with pytest.raises(
        LLMProviderError,
        match="must remain local",
    ):
        OllamaProvider(
            base_url="http://example.com:11434"
        )


def test_stage7o_ollama_provider_rejects_https_endpoint() -> None:
    import pytest

    from operations.stage7o.llm import (
        LLMProviderError,
    )
    from operations.stage7o.providers.ollama import (
        OllamaProvider,
    )

    with pytest.raises(
        LLMProviderError,
        match="must use local HTTP",
    ):
        OllamaProvider(
            base_url="https://localhost:11434"
        )


def test_stage7o_ollama_provider_fails_closed_on_incomplete_response() -> None:
    import asyncio
    import pytest

    from operations.stage7o.llm import (
        LLMProviderError,
    )
    from operations.stage7o.providers.ollama import (
        OllamaProvider,
    )

    fake = _FakeOllamaClient(
        _FakeOllamaResponse(
            payload={
                "model": "qwen3:4b",
                "done": False,
                "response": "partial",
            }
        )
    )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        client=fake,
    )

    with pytest.raises(
        LLMProviderError,
        match="did not complete",
    ):
        asyncio.run(
            provider.generate(
                _stage7o_ollama_request()
            )
        )


def test_stage7o_ollama_provider_requires_no_secret_or_paid_api() -> None:
    from pathlib import Path

    provider_source = Path(
        "operations/stage7o/providers/ollama.py"
    ).read_text(encoding="utf-8").lower()

    assert "openai_api_key" not in provider_source
    assert "authorization" not in provider_source
    assert "bearer" not in provider_source
    assert "api_key" not in provider_source

    assert "host.docker.internal:11434" in provider_source


def test_stage7o_provider_factory_builds_ollama_without_api_key(
    monkeypatch,
) -> None:
    from operations.stage7o.provider_factory import (
        build_llm_provider,
        provider_runtime_metadata,
    )
    from operations.stage7o.providers.ollama import (
        OllamaProvider,
    )

    monkeypatch.setenv(
        "PHARMSTOCK_STAGE7O_LLM_PROVIDER",
        "ollama",
    )
    monkeypatch.delenv(
        "PHARMSTOCK_STAGE7O_OPENAI_API_KEY",
        raising=False,
    )
    monkeypatch.setenv(
        "PHARMSTOCK_STAGE7O_OLLAMA_BASE_URL",
        "http://127.0.0.1:11434",
    )
    monkeypatch.setenv(
        "PHARMSTOCK_STAGE7O_OLLAMA_MODEL",
        "qwen3:4b",
    )

    provider = build_llm_provider()

    assert isinstance(
        provider,
        OllamaProvider,
    )

    assert provider.base_url == (
        "http://127.0.0.1:11434"
    )
    assert provider.model == "qwen3:4b"

    metadata = provider_runtime_metadata(
        provider
    )

    assert metadata["configured_selection"] == (
        "ollama"
    )
    assert metadata["provider"] == (
        "OLLAMA_LOCAL"
    )
    assert metadata["model"] == "qwen3:4b"
    assert metadata["configured"] is True
    assert metadata["api_key_present"] is False


def test_stage7o_provider_factory_ollama_uses_safe_defaults(
    monkeypatch,
) -> None:
    from operations.stage7o.provider_factory import (
        build_llm_provider,
    )
    from operations.stage7o.providers.ollama import (
        OllamaProvider,
    )

    monkeypatch.setenv(
        "PHARMSTOCK_STAGE7O_LLM_PROVIDER",
        "ollama",
    )
    monkeypatch.delenv(
        "PHARMSTOCK_STAGE7O_OLLAMA_BASE_URL",
        raising=False,
    )
    monkeypatch.delenv(
        "PHARMSTOCK_STAGE7O_OLLAMA_MODEL",
        raising=False,
    )

    provider = build_llm_provider()

    assert isinstance(
        provider,
        OllamaProvider,
    )

    assert provider.base_url == (
        "http://host.docker.internal:11434"
    )
    assert provider.model == "qwen3:4b"


def test_stage7o_provider_factory_ollama_rejects_remote_endpoint(
    monkeypatch,
) -> None:
    import pytest

    from operations.stage7o.llm import (
        LLMProviderError,
    )
    from operations.stage7o.provider_factory import (
        build_llm_provider,
    )

    monkeypatch.setenv(
        "PHARMSTOCK_STAGE7O_LLM_PROVIDER",
        "ollama",
    )
    monkeypatch.setenv(
        "PHARMSTOCK_STAGE7O_OLLAMA_BASE_URL",
        "http://example.com:11434",
    )

    with pytest.raises(
        LLMProviderError,
        match="must remain local",
    ):
        build_llm_provider()


def test_build_reorder_grounded_evidence():
    from operations.stage7o.explainer import (
        build_reorder_grounded_evidence,
    )

    plan = {
        "evidence": [
            {
                "tool": "inventory_context",
                "read_only": True,
                "data": {
                    "items": [
                        {
                            "branch_id": "branch-1",
                            "branch_code": "BR-001",
                            "branch_name": "Synthetic Branch",
                            "product_id": "product-1",
                            "trade_name_en": "Test Product",
                            "scientific_name": "Test Ingredient",
                            "available_units": 0,
                            "reorder_point_units": 5,
                            "target_stock_units": 12,
                            "zero_stock": True,
                            "below_reorder": True,
                        }
                    ]
                },
            },
            {
                "tool": "ml_signals",
                "read_only": True,
                "data": {
                    "items": [
                        {
                            "model_key": (
                                "reorder_recommendation"
                            ),
                            "model_version": "v6",
                            "prediction_value": 65,
                            "action_required": True,
                        }
                    ]
                },
            },
            {
                "tool": "decision_cases",
                "read_only": True,
                "data": {
                    "items": [
                        {
                            "decision_type": "REORDER",
                            "status": "APPROVED_DRAFT",
                            "recommended_units": 65,
                            "approval_required": True,
                            "supplier_selected": False,
                            "automatic_po_allowed": False,
                        }
                    ]
                },
            },
        ]
    }

    grounded = build_reorder_grounded_evidence(
        plan
    )

    assert len(grounded) == 4

    explanation_item = grounded[-1]

    assert (
        explanation_item["tool"]
        == "deterministic_reorder_explanation"
    )
    assert explanation_item["read_only"] is True

    explanation = explanation_item["data"]

    assert explanation["recommended_units"] == 65
    assert (
        explanation["exact_quantity_explainable"]
        is False
    )

    facts = {
        item["fact"]: item.get("value")
        for item in explanation["facts"]
    }

    assert facts["available_inventory"] == 0
    assert facts["reorder_point"] == 5
    assert facts["target_stock"] == 12
    assert facts["zero_stock"] is True
    assert facts["below_reorder"] is True
    assert facts["model_recommendation"] == 65

    governance = explanation["governance"]

    assert governance["read_only"] is True
    assert (
        governance["human_approval_required"]
        is True
    )
    assert (
        governance[
            "automatic_supplier_selection"
        ]
        is False
    )
    assert (
        governance[
            "automatic_purchase_order_creation"
        ]
        is False
    )
    assert (
        governance[
            "procurement_execution_allowed"
        ]
        is False
    )


def test_finalize_grounded_reorder_answer_blocks_causal_claim():
    from operations.stage7o.llm import (
        GroundedLLMRequest,
        finalize_grounded_answer,
    )

    disclosure = (
        "Operational evidence is SYNTHETIC_CALIBRATED "
        "and must not be described as live or real "
        "pharmacy operations."
    )

    request = GroundedLLMRequest(
        question="Why did the model recommend 65 units?",
        evidence=[
            {
                "tool": "deterministic_reorder_explanation",
                "read_only": True,
                "data": {
                    "recommended_units": 65,
                    "exact_quantity_explainable": False,
                    "facts": [
                        {
                            "fact": "available_inventory",
                            "value": 0,
                        },
                        {
                            "fact": "reorder_point",
                            "value": 5,
                        },
                        {
                            "fact": "target_stock",
                            "value": 12,
                        },
                    ],
                },
            }
        ],
        data_context={
            "contains_synthetic_operational_data": True,
            "safe_to_describe_as_live_operational": False,
            "assistant_disclosure_required": True,
            "disclosure": disclosure,
        },
        governance={
            "direct_database_access": False,
            "assistant_mutations_allowed": False,
            "automatic_supplier_selection": False,
            "automatic_purchase_order_creation": False,
            "procurement_execution_allowed": False,
        },
    )

    unsafe_generated = (
        "The 65 units are a direct result of zero stock "
        "and the reorder point."
    )

    answer = finalize_grounded_answer(
        request,
        unsafe_generated,
    )

    assert "direct result" not in answer
    assert "available inventory is 0 units" in answer
    assert "reorder point is 5 units" in answer
    assert "target-stock value is 12 units" in answer
    assert "recommended 65 units" in answer
    assert (
        "does not contain feature attribution or a "
        "quantity formula sufficient to prove why the "
        "recommendation is exactly 65 units"
        in answer
    )
    assert answer.count(disclosure) == 1


def test_finalize_grounded_answer_deduplicates_disclosure():
    from operations.stage7o.llm import (
        GroundedLLMRequest,
        finalize_grounded_answer,
    )

    disclosure = (
        "Operational evidence is SYNTHETIC_CALIBRATED "
        "and must not be described as live or real "
        "pharmacy operations."
    )

    request = GroundedLLMRequest(
        question="Summarize the evidence.",
        evidence=[
            {
                "tool": "inventory_context",
                "read_only": True,
                "data": {"items": []},
            }
        ],
        data_context={
            "contains_synthetic_operational_data": True,
            "safe_to_describe_as_live_operational": False,
            "assistant_disclosure_required": True,
            "disclosure": disclosure,
        },
        governance={
            "direct_database_access": False,
            "assistant_mutations_allowed": False,
            "automatic_supplier_selection": False,
            "automatic_purchase_order_creation": False,
            "procurement_execution_allowed": False,
        },
    )

    generated = (
        disclosure
        + "\n\nNo matching inventory records were found.\n\n"
        + disclosure
    )

    answer = finalize_grounded_answer(
        request,
        generated,
    )

    assert answer.count(disclosure) == 1
    assert (
        "No matching inventory records were found."
        in answer
    )


def test_ollama_provider_applies_deterministic_reorder_finalizer():
    import asyncio

    import httpx

    from operations.stage7o.llm import (
        GroundedLLMRequest,
    )
    from operations.stage7o.providers.ollama import (
        OllamaProvider,
    )

    disclosure = (
        "Operational evidence is SYNTHETIC_CALIBRATED "
        "and must not be described as live or real "
        "pharmacy operations."
    )

    request = GroundedLLMRequest(
        question="Why did the model recommend 65 units?",
        evidence=[
            {
                "tool": (
                    "deterministic_reorder_explanation"
                ),
                "read_only": True,
                "data": {
                    "recommended_units": 65,
                    "exact_quantity_explainable": False,
                    "facts": [
                        {
                            "fact": "available_inventory",
                            "value": 0,
                        },
                        {
                            "fact": "reorder_point",
                            "value": 5,
                        },
                        {
                            "fact": "target_stock",
                            "value": 12,
                        },
                    ],
                },
            }
        ],
        data_context={
            "contains_synthetic_operational_data": True,
            "safe_to_describe_as_live_operational": False,
            "assistant_disclosure_required": True,
            "disclosure": disclosure,
        },
        governance={
            "direct_database_access": False,
            "assistant_mutations_allowed": False,
            "automatic_supplier_selection": False,
            "automatic_purchase_order_creation": False,
            "procurement_execution_allowed": False,
        },
    )

    async def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "qwen3:4b",
                "done": True,
                "response": (
                    "The 65 units are a direct result "
                    "of zero stock and the reorder point."
                ),
            },
        )

    transport = httpx.MockTransport(handler)

    async def run_test():
        async with httpx.AsyncClient(
            transport=transport
        ) as client:
            provider = OllamaProvider(
                base_url="http://localhost:11434",
                model="qwen3:4b",
                client=client,
            )

            return await provider.generate(
                request
            )

    answer = asyncio.run(run_test())

    assert answer.provider == "OLLAMA_LOCAL"
    assert answer.model == "qwen3:4b"

    assert "direct result" not in answer.text

    assert (
        "available inventory is 0 units"
        in answer.text
    )
    assert (
        "reorder point is 5 units"
        in answer.text
    )
    assert (
        "target-stock value is 12 units"
        in answer.text
    )
    assert (
        "recommended 65 units"
        in answer.text
    )

    assert (
        "does not contain feature attribution or a "
        "quantity formula sufficient to prove why the "
        "recommendation is exactly 65 units"
        in answer.text
    )

    assert answer.text.count(disclosure) == 1


def test_stage7o_router_supported_intents():
    from operations.stage7o.router import (
        AssistantIntent,
        route_question,
    )

    cases = [
        (
            "Which branches have highest stockout risk?",
            AssistantIntent.HIGHEST_STOCKOUT_RISK,
            ["ml_signals"],
            {},
        ),
        (
            "Why did the model recommend 65 units?",
            AssistantIntent.REORDER_EXPLANATION,
            [
                "inventory_context",
                "ml_signals",
                "decision_cases",
            ],
            {
                "branch_id": "branch-1",
                "product_id": "product-1",
            },
        ),
        (
            "Show approved replenishment drafts.",
            AssistantIntent.APPROVED_REPLENISHMENT_DRAFTS,
            ["decision_cases"],
            {},
        ),
        (
            "Which suppliers have worst lead time?",
            AssistantIntent.WORST_SUPPLIER_LEAD_TIME,
            ["supplier_performance"],
            {},
        ),
        (
            "What changed in demand?",
            AssistantIntent.DEMAND_CHANGE,
            ["demand_trend"],
            {},
        ),
        (
            "Explain CRITICAL stockout signal.",
            AssistantIntent.CRITICAL_STOCKOUT_SIGNAL,
            [
                "ml_signals",
                "decision_cases",
            ],
            {},
        ),
        (
            "What actions require human approval?",
            AssistantIntent.HUMAN_APPROVAL_ACTIONS,
            ["decision_cases"],
            {},
        ),
    ]

    for (
        question,
        expected_intent,
        expected_tools,
        scope,
    ) in cases:
        route = route_question(
            question,
            **scope,
        )

        assert route.intent == expected_intent

        assert [
            call.tool_name
            for call in route.calls
        ] == expected_tools


def test_stage7o_router_reorder_requires_pair_scope():
    import pytest

    from operations.stage7o.router import (
        AssistantRoutingError,
        route_question,
    )

    with pytest.raises(
        AssistantRoutingError,
        match=(
            "requires both branch_id and product_id"
        ),
    ):
        route_question(
            "Why did the model recommend 65 units?"
        )

    with pytest.raises(
        AssistantRoutingError,
        match=(
            "requires both branch_id and product_id"
        ),
    ):
        route_question(
            "Explain the recommendation.",
            branch_id="branch-1",
        )


def test_stage7o_router_unknown_intent_fails_closed():
    import pytest

    from operations.stage7o.router import (
        AssistantRoutingError,
        route_question,
    )

    with pytest.raises(
        AssistantRoutingError,
        match="UNKNOWN_INTENT",
    ):
        route_question(
            "Tell me a joke about pharmacies."
        )


def test_stage7o_router_plans_are_governed_read_only_tools():
    from operations.stage7o.orchestrator import (
        validate_plan,
    )
    from operations.stage7o.router import (
        route_question,
    )
    from operations.stage7o.tools import TOOLS

    questions = [
        (
            "Which branches have highest stockout risk?",
            {},
        ),
        (
            "Why did the model recommend 65 units?",
            {
                "branch_id": "branch-1",
                "product_id": "product-1",
            },
        ),
        (
            "Show approved replenishment drafts.",
            {},
        ),
        (
            "Which suppliers have worst lead time?",
            {},
        ),
        (
            "What changed in demand?",
            {},
        ),
        (
            "Explain CRITICAL stockout signal.",
            {},
        ),
        (
            "What actions require human approval?",
            {},
        ),
    ]

    for question, scope in questions:
        route = route_question(
            question,
            **scope,
        )

        validated = validate_plan(
            route.calls
        )

        assert validated

        for call in validated:
            assert call.tool_name in TOOLS
            assert call.tool_name not in {
                "create_purchase_order",
                "select_supplier",
                "execute_procurement",
            }


def test_stage7o_ask_endpoint_routes_and_answers():
    from fastapi.testclient import TestClient

    from operations.stage7o import api as api_module
    from operations.stage7o.llm import LLMAnswer


    class FakeStage7MClient:
        api_key_configured = True

        async def close(self):
            return None

        async def inventory(self, params):
            return {
                "items": [
                    {
                        "branch_id": "branch-1",
                        "branch_code": "BR-001",
                        "branch_name": "Synthetic Branch",
                        "product_id": "product-1",
                        "trade_name_en": "Test Product",
                        "scientific_name": "Test Ingredient",
                        "available_units": 0,
                        "reorder_point_units": 5,
                        "target_stock_units": 12,
                        "zero_stock": True,
                        "below_reorder": True,
                        "operational_provenance_class":
                            "SYNTHETIC_CALIBRATED",
                        "reference_provenance_class":
                            "PUBLIC_MARKET_EGYPT",
                    }
                ]
            }

        async def ml_signals(self, params):
            return {
                "items": [
                    {
                        "branch_id": "branch-1",
                        "product_id": "product-1",
                        "model_key":
                            "reorder_recommendation",
                        "model_version": "v6",
                        "prediction_value": 65,
                        "action_required": True,
                        "operational_provenance_class":
                            "SYNTHETIC_CALIBRATED",
                        "reference_provenance_class":
                            "PUBLIC_MARKET_EGYPT",
                    }
                ]
            }

        async def cases(self, params):
            return {
                "items": [
                    {
                        "branch_id": "branch-1",
                        "product_id": "product-1",
                        "decision_type": "REORDER",
                        "status": "APPROVED_DRAFT",
                        "recommended_units": 65,
                        "approval_required": True,
                        "supplier_selected": False,
                        "automatic_po_allowed": False,
                        "operational_provenance_class":
                            "SYNTHETIC_CALIBRATED",
                        "reference_provenance_class":
                            "PUBLIC_MARKET_EGYPT",
                    }
                ]
            }


    class FakeLLMProvider:
        name = "FAKE_PROVIDER"

        async def generate(self, request):
            return LLMAnswer(
                text=(
                    "Operational evidence is "
                    "SYNTHETIC_CALIBRATED and must not "
                    "be described as live or real "
                    "pharmacy operations."
                ),
                provider=self.name,
                model="fake-model",
            )


    @asynccontextmanager
    async def fake_lifespan(app):
        app.state.stage7m_client = FakeStage7MClient()
        app.state.llm_provider = FakeLLMProvider()
        yield


    original_lifespan = (
        api_module.app.router.lifespan_context
    )

    api_module.app.router.lifespan_context = (
        fake_lifespan
    )

    try:
        with TestClient(api_module.app) as client:
            response = client.post(
                "/v1/assistant/ask",
                json={
                    "question": (
                        "Why did the model recommend "
                        "65 units?"
                    ),
                    "branch_id": "branch-1",
                    "product_id": "product-1",
                },
            )

            assert response.status_code == 200

            payload = response.json()

            assert payload["status"] == "OK"
            assert (
                payload["intent"]
                == "REORDER_EXPLANATION"
            )
            assert payload["provider"] == "DETERMINISTIC"
            assert payload["model"] == "CANONICAL_GROUNDED"
            assert payload["tool_call_count"] == 3
            assert payload["read_only"] is True

            governance = payload["governance"]

            assert (
                governance[
                    "assistant_mutations_allowed"
                ]
                is False
            )
            assert (
                governance[
                    "automatic_supplier_selection"
                ]
                is False
            )
            assert (
                governance[
                    "automatic_purchase_order_creation"
                ]
                is False
            )

            data_context = payload["data_context"]

            assert (
                data_context[
                    "operational_context"
                ]
                == "SYNTHETIC_OPERATIONAL"
            )
            assert (
                data_context[
                    "safe_to_describe_as_live_operational"
                ]
                is False
            )

    finally:
        api_module.app.router.lifespan_context = (
            original_lifespan
        )


def test_stage7o_ask_endpoint_unknown_intent_returns_422():
    from fastapi.testclient import TestClient

    from operations.stage7o import api as api_module


    class FakeStage7MClient:
        api_key_configured = True

        async def close(self):
            return None


    class FakeLLMProvider:
        name = "FAKE_PROVIDER"


    @asynccontextmanager
    async def fake_lifespan(app):
        app.state.stage7m_client = FakeStage7MClient()
        app.state.llm_provider = FakeLLMProvider()
        yield


    original_lifespan = (
        api_module.app.router.lifespan_context
    )

    api_module.app.router.lifespan_context = (
        fake_lifespan
    )

    try:
        with TestClient(api_module.app) as client:
            response = client.post(
                "/v1/assistant/ask",
                json={
                    "question":
                        "Tell me a joke about pharmacies."
                },
            )

            assert response.status_code == 422

            payload = response.json()

            assert payload["status"] == "REJECTED"
            assert (
                payload["error_type"]
                == "ROUTING_ERROR"
            )
            assert "UNKNOWN_INTENT" in payload["detail"]
            assert payload["read_only"] is True

    finally:
        api_module.app.router.lifespan_context = (
            original_lifespan
        )


def test_stage7o_ask_endpoint_reorder_scope_required():
    from fastapi.testclient import TestClient

    from operations.stage7o import api as api_module


    class FakeStage7MClient:
        api_key_configured = True

        async def close(self):
            return None


    class FakeLLMProvider:
        name = "FAKE_PROVIDER"


    @asynccontextmanager
    async def fake_lifespan(app):
        app.state.stage7m_client = FakeStage7MClient()
        app.state.llm_provider = FakeLLMProvider()
        yield


    original_lifespan = (
        api_module.app.router.lifespan_context
    )

    api_module.app.router.lifespan_context = (
        fake_lifespan
    )

    try:
        with TestClient(api_module.app) as client:
            response = client.post(
                "/v1/assistant/ask",
                json={
                    "question": (
                        "Why did the model recommend "
                        "65 units?"
                    )
                },
            )

            assert response.status_code == 422

            payload = response.json()

            assert (
                payload["error_type"]
                == "ROUTING_ERROR"
            )
            assert (
                "requires both branch_id and product_id"
                in payload["detail"]
            )

    finally:
        api_module.app.router.lifespan_context = (
            original_lifespan
        )


def test_build_stockout_ranking_grounded_evidence():
    from operations.stage7o.explainer import (
        build_stockout_ranking_grounded_evidence,
    )

    plan = {
        "evidence": [
            {
                "tool": "ml_signals",
                "read_only": True,
                "data": {
                    "items": [
                        {
                            "model_key": "stockout_risk",
                            "branch_id": "branch-a",
                            "branch_code": "BR-A",
                            "branch_name": "Branch A",
                            "product_id": "product-a",
                            "trade_name_en": "Product A",
                            "probability": 0.20,
                            "severity": "CRITICAL",
                            "action_required": False,
                        },
                        {
                            "model_key": "stockout_risk",
                            "branch_id": "branch-b",
                            "branch_code": "BR-B",
                            "branch_name": "Branch B",
                            "product_id": "product-b",
                            "trade_name_en": "Product B",
                            "probability": 0.75,
                            "severity": "HIGH",
                            "action_required": True,
                        },
                        {
                            "model_key": "stockout_risk",
                            "branch_id": "branch-c",
                            "branch_code": "BR-C",
                            "branch_name": "Branch C",
                            "product_id": "product-c",
                            "trade_name_en": "Product C",
                            "probability": 0.45,
                            "severity": "CRITICAL",
                            "action_required": True,
                        },
                    ]
                },
            }
        ]
    }

    grounded = (
        build_stockout_ranking_grounded_evidence(
            plan
        )
    )

    assert len(grounded) == 2

    ranking = grounded[-1]

    assert (
        ranking["tool"]
        == "deterministic_stockout_probability_ranking"
    )
    assert ranking["read_only"] is True

    data = ranking["data"]

    assert data["ranking_basis"] == "probability_desc"
    assert data["result_count"] == 3

    items = data["items"]

    assert [item["rank"] for item in items] == [1, 2, 3]

    assert [
        item["branch_code"]
        for item in items
    ] == [
        "BR-B",
        "BR-C",
        "BR-A",
    ]

    assert [
        item["probability"]
        for item in items
    ] == [
        0.75,
        0.45,
        0.20,
    ]


def test_finalize_stockout_ranking_blocks_network_wide_claim():
    from operations.stage7o.llm import (
        GroundedLLMRequest,
        finalize_grounded_answer,
    )

    disclosure = (
        "Operational evidence is SYNTHETIC_CALIBRATED "
        "and must not be described as live or real "
        "pharmacy operations."
    )

    request = GroundedLLMRequest(
        question=(
            "Which branches have highest stockout risk?"
        ),
        evidence=[
            {
                "tool": (
                    "deterministic_stockout_probability_ranking"
                ),
                "read_only": True,
                "data": {
                    "ranking_basis": "probability_desc",
                    "result_count": 2,
                    "ranking_scope": (
                        "currently returned governed "
                        "stockout-risk signals"
                    ),
                    "items": [
                        {
                            "rank": 1,
                            "branch_code": "BR-B",
                            "branch_name": "Branch B",
                            "trade_name_en": "Product B",
                            "probability": 0.75,
                            "severity": "CRITICAL",
                        },
                        {
                            "rank": 2,
                            "branch_code": "BR-A",
                            "branch_name": "Branch A",
                            "trade_name_en": "Product A",
                            "probability": 0.20,
                            "severity": "HIGH",
                        },
                    ],
                },
            }
        ],
        data_context={
            "contains_synthetic_operational_data": True,
            "safe_to_describe_as_live_operational": False,
            "assistant_disclosure_required": True,
            "disclosure": disclosure,
        },
        governance={
            "direct_database_access": False,
            "assistant_mutations_allowed": False,
            "automatic_supplier_selection": False,
            "automatic_purchase_order_creation": False,
            "procurement_execution_allowed": False,
        },
    )

    unsafe_generated = (
        "Branch B has the highest stockout risk "
        "in the entire pharmacy network."
    )

    answer = finalize_grounded_answer(
        request,
        unsafe_generated,
    )

    lower = answer.lower()

    assert "entire pharmacy network" not in lower
    assert "network-wide ranking" in lower
    assert (
        "among the 2 currently returned governed "
        "stockout-risk signals"
        in lower
    )
    assert "branch b" in lower
    assert "0.750000" in answer
    assert "severity CRITICAL" in answer
    assert answer.count(disclosure) == 1


def test_build_supplier_lead_time_grounded_evidence():
    from operations.stage7o.explainer import (
        build_supplier_lead_time_grounded_evidence,
    )

    plan = {
        "evidence": [
            {
                "tool": "supplier_performance",
                "read_only": True,
                "data": {
                    "items": [
                        {
                            "supplier_id": "supplier-a",
                            "supplier_code": "SUP-A",
                            "supplier_name": "Supplier A",
                            "avg_actual_lead_time_days": 8.0,
                            "delayed_receipt_rate": 0.20,
                            "reliability_score": 0.95,
                        },
                        {
                            "supplier_id": "supplier-b",
                            "supplier_code": "SUP-B",
                            "supplier_name": "Supplier B",
                            "avg_actual_lead_time_days": 14.0,
                            "delayed_receipt_rate": 0.10,
                            "reliability_score": 0.90,
                        },
                        {
                            "supplier_id": "supplier-c",
                            "supplier_code": "SUP-C",
                            "supplier_name": "Supplier C",
                            "avg_actual_lead_time_days": 14.0,
                            "delayed_receipt_rate": 0.35,
                            "reliability_score": 0.88,
                        },
                    ]
                },
            }
        ]
    }

    grounded = (
        build_supplier_lead_time_grounded_evidence(
            plan
        )
    )

    assert len(grounded) == 2

    ranking = grounded[-1]

    assert (
        ranking["tool"]
        == "deterministic_supplier_lead_time_ranking"
    )
    assert ranking["read_only"] is True

    data = ranking["data"]

    assert data["result_count"] == 3

    items = data["items"]

    assert [
        item["rank"]
        for item in items
    ] == [1, 2, 3]

    assert [
        item["supplier_code"]
        for item in items
    ] == [
        "SUP-C",
        "SUP-B",
        "SUP-A",
    ]

    assert [
        item["avg_actual_lead_time_days"]
        for item in items
    ] == [
        14.0,
        14.0,
        8.0,
    ]

    assert [
        item["delayed_receipt_rate"]
        for item in items
    ] == [
        0.35,
        0.10,
        0.20,
    ]


def test_finalize_supplier_lead_time_blocks_hallucinated_metrics():
    from operations.stage7o.llm import (
        GroundedLLMRequest,
        finalize_grounded_answer,
    )

    disclosure = (
        "Operational evidence is SYNTHETIC_CALIBRATED "
        "and must not be described as live or real "
        "pharmacy operations."
    )

    request = GroundedLLMRequest(
        question=(
            "Which suppliers have worst lead time?"
        ),
        evidence=[
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
                    "result_count": 2,
                    "ranking_scope": (
                        "currently returned governed "
                        "supplier-performance records"
                    ),
                    "items": [
                        {
                            "rank": 1,
                            "supplier_code": "SUP-X",
                            "supplier_name": "Supplier X",
                            "avg_actual_lead_time_days": 21.5,
                            "delayed_receipt_rate": 0.40,
                            "reliability_score": 0.82,
                        },
                        {
                            "rank": 2,
                            "supplier_code": "SUP-Y",
                            "supplier_name": "Supplier Y",
                            "avg_actual_lead_time_days": 12.0,
                            "delayed_receipt_rate": 0.10,
                            "reliability_score": 0.95,
                        },
                    ],
                },
            }
        ],
        data_context={
            "contains_synthetic_operational_data": True,
            "safe_to_describe_as_live_operational": False,
            "assistant_disclosure_required": True,
            "disclosure": disclosure,
        },
        governance={
            "direct_database_access": False,
            "assistant_mutations_allowed": False,
            "automatic_supplier_selection": False,
            "automatic_purchase_order_creation": False,
            "procurement_execution_allowed": False,
        },
    )

    unsafe_generated = (
        "There are 9 suppliers. The average lead time "
        "is 15 days and Supplier Y is the best choice."
    )

    answer = finalize_grounded_answer(
        request,
        unsafe_generated,
    )

    lower = answer.lower()

    assert "9 suppliers" not in lower
    assert "average lead time is 15 days" not in lower
    assert "best choice" not in lower

    assert (
        "among the 2 currently returned governed "
        "supplier-performance records"
        in lower
    )
    assert "supplier x" in lower
    assert "21.50 days" in answer
    assert "0.400000" in answer
    assert "0.820000" in answer

    assert "no supplier was selected" in lower
    assert "no purchase order" in lower

    assert answer.count(disclosure) == 1


def test_build_demand_trend_grounded_evidence():
    from operations.stage7o.explainer import (
        build_demand_trend_grounded_evidence,
    )

    plan = {
        "evidence": [
            {
                "tool": "demand_trend",
                "read_only": True,
                "data": {
                    "operational_data_as_of":
                        "2026-09-02",
                    "analytical_state": [
                        {
                            "provenance_class":
                                "SYNTHETIC_CALIBRATED",
                            "analytical_as_of_date":
                                "2026-08-22",
                        }
                    ],
                    "scope": "NETWORK",
                    "items": [
                        {
                            "business_date":
                                "2026-08-09",
                            "requested_units": 333762,
                            "fill_rate": 0.980210,
                        },
                        {
                            "business_date":
                                "2026-08-14",
                            "requested_units": 282646,
                            "fill_rate": 0.980191,
                        },
                        {
                            "business_date":
                                "2026-08-21",
                            "requested_units": 282493,
                            "fill_rate": 0.980828,
                        },
                        {
                            "business_date":
                                "2026-08-22",
                            "requested_units": 309040,
                            "fill_rate": 0.979902,
                        },
                    ],
                },
            }
        ]
    }

    grounded = (
        build_demand_trend_grounded_evidence(
            plan
        )
    )

    assert len(grounded) == 2

    summary_item = grounded[-1]

    assert (
        summary_item["tool"]
        == "deterministic_demand_trend_summary"
    )
    assert summary_item["read_only"] is True

    summary = summary_item["data"]

    assert (
        summary["analytical_as_of_date"]
        == "2026-08-22"
    )
    assert (
        summary["operational_data_as_of"]
        == "2026-09-02"
    )
    assert summary["scope"] == "NETWORK"
    assert summary["day_count"] == 4

    assert (
        summary["start_requested_units"]
        == 333762
    )
    assert (
        summary["end_requested_units"]
        == 309040
    )

    assert (
        summary[
            "absolute_change_requested_units"
        ]
        == -24722.0
    )

    assert (
        summary[
            "minimum_requested_units"
        ]["business_date"]
        == "2026-08-21"
    )
    assert (
        summary[
            "minimum_requested_units"
        ]["value"]
        == 282493
    )

    assert (
        summary[
            "maximum_requested_units"
        ]["business_date"]
        == "2026-08-09"
    )
    assert (
        summary[
            "maximum_requested_units"
        ]["value"]
        == 333762
    )

    assert (
        summary["minimum_fill_rate"]
        == 0.979902
    )
    assert (
        summary["maximum_fill_rate"]
        == 0.980828
    )


def test_finalize_demand_trend_blocks_unsupported_causal_narrative():
    from operations.stage7o.llm import (
        GroundedLLMRequest,
        finalize_grounded_answer,
    )

    disclosure = (
        "Operational evidence is SYNTHETIC_CALIBRATED "
        "and must not be described as live or real "
        "pharmacy operations."
    )

    request = GroundedLLMRequest(
        question="What changed in demand?",
        evidence=[
            {
                "tool": (
                    "deterministic_demand_trend_summary"
                ),
                "read_only": True,
                "data": {
                    "scope": "NETWORK",
                    "operational_data_as_of":
                        "2026-09-02",
                    "analytical_as_of_date":
                        "2026-08-22",
                    "day_count": 14,
                    "start_date": "2026-08-09",
                    "start_requested_units": 333762,
                    "end_date": "2026-08-22",
                    "end_requested_units": 309040,
                    "absolute_change_requested_units":
                        -24722.0,
                    "percent_change_requested_units":
                        -7.407250,
                    "minimum_requested_units": {
                        "business_date":
                            "2026-08-21",
                        "value": 282493,
                    },
                    "maximum_requested_units": {
                        "business_date":
                            "2026-08-18",
                        "value": 334865,
                    },
                    "minimum_fill_rate":
                        0.979628,
                    "maximum_fill_rate":
                        0.980828,
                    "average_fill_rate":
                        0.980174,
                },
            }
        ],
        data_context={
            "contains_synthetic_operational_data": True,
            "safe_to_describe_as_live_operational": False,
            "assistant_disclosure_required": True,
            "disclosure": disclosure,
        },
        governance={
            "direct_database_access": False,
            "assistant_mutations_allowed": False,
            "automatic_supplier_selection": False,
            "automatic_purchase_order_creation": False,
            "procurement_execution_allowed": False,
        },
    )

    unsafe_generated = (
        "Demand dropped because of a public holiday "
        "and then recovered after a marketing campaign."
    )

    answer = finalize_grounded_answer(
        request,
        unsafe_generated,
    )

    lower = answer.lower()

    assert "public holiday" not in lower
    assert "marketing campaign" not in lower
    assert "infer causes" in lower

    assert "2026-08-22" in answer
    assert "333762" in answer
    assert "309040" in answer
    assert "24722" in answer
    assert "-7.41%" in answer
    assert "282493" in answer
    assert "334865" in answer

    assert "97.96%" in answer
    assert "98.08%" in answer

    assert answer.count(disclosure) == 1


def test_build_critical_stockout_grounded_evidence():
    from operations.stage7o.explainer import (
        build_critical_stockout_grounded_evidence,
    )

    plan = {
        "evidence": [
            {
                "tool": "ml_signals",
                "read_only": True,
                "data": {
                    "items": [
                        {
                            "branch_id": "branch-1",
                            "branch_code": "BR-001",
                            "branch_name": "Synthetic Branch",
                            "product_id": "product-1",
                            "trade_name_en": "Test Product",
                            "scientific_name": "Test Ingredient",
                            "model_key": "stockout_risk",
                            "model_version": "6",
                            "severity": "CRITICAL",
                            "probability": 0.032890885425,
                            "threshold": 0.001920516347,
                            "action_required": False,
                        }
                    ]
                },
            },
            {
                "tool": "decision_cases",
                "read_only": True,
                "data": {
                    "items": [
                        {
                            "branch_id": "branch-1",
                            "branch_code": "BR-001",
                            "branch_name": "Synthetic Branch",
                            "product_id": "product-1",
                            "trade_name_en": "Test Product",
                            "decision_type": "STOCKOUT",
                            "model_key": "stockout_risk",
                            "model_version": "6",
                            "severity": "CRITICAL",
                            "probability": 0.032890885425,
                            "threshold": 0.001920516347,
                            "action_required": False,
                            "status": "CLOSED",
                            "resolution_code": "MODEL_CLEARED",
                            "approval_required": True,
                            "auto_execution_allowed": False,
                        }
                    ]
                },
            },
        ]
    }

    grounded = (
        build_critical_stockout_grounded_evidence(
            plan
        )
    )

    assert len(grounded) == 3

    item = grounded[-1]

    assert (
        item["tool"]
        == "deterministic_critical_stockout_explanation"
    )
    assert item["read_only"] is True

    data = item["data"]

    assert data["severity"] == "CRITICAL"
    assert (
        data["probability"]
        == 0.032890885425
    )
    assert (
        data["threshold"]
        == 0.001920516347
    )

    assert (
        data["probability_above_threshold"]
        is True
    )

    assert data["threshold_multiple"] > 17.0
    assert data["threshold_multiple"] < 17.2

    assert data["action_required"] is False
    assert data["case_status"] == "CLOSED"
    assert (
        data["resolution_code"]
        == "MODEL_CLEARED"
    )
    assert data["approval_required"] is True
    assert (
        data["auto_execution_allowed"]
        is False
    )

    assert (
        "action_required=false"
        in data["interpretation"]
    )

    assert (
        "must not be presented as "
        "retroactively invalidating"
        in data["case_lifecycle_limitation"]
    )


def test_finalize_critical_stockout_blocks_misleading_cleared_claim():
    from operations.stage7o.llm import (
        GroundedLLMRequest,
        finalize_grounded_answer,
    )

    disclosure = (
        "Operational evidence is SYNTHETIC_CALIBRATED "
        "and must not be described as live or real "
        "pharmacy operations."
    )

    request = GroundedLLMRequest(
        question="Explain CRITICAL stockout signal.",
        evidence=[
            {
                "tool": (
                    "deterministic_critical_stockout_explanation"
                ),
                "read_only": True,
                "data": {
                    "branch_code": "BR-001",
                    "branch_name": "Synthetic Branch",
                    "trade_name_en": "Test Product",
                    "severity": "CRITICAL",
                    "probability": 0.032890885425,
                    "threshold": 0.001920516347,
                    "probability_above_threshold": True,
                    "threshold_multiple": 17.126,
                    "action_required": False,
                    "case_status": "CLOSED",
                    "resolution_code": "MODEL_CLEARED",
                    "approval_required": True,
                    "auto_execution_allowed": False,
                },
            }
        ],
        data_context={
            "contains_synthetic_operational_data": True,
            "safe_to_describe_as_live_operational": False,
            "assistant_disclosure_required": True,
            "disclosure": disclosure,
        },
        governance={
            "direct_database_access": False,
            "assistant_mutations_allowed": False,
            "automatic_supplier_selection": False,
            "automatic_purchase_order_creation": False,
            "procurement_execution_allowed": False,
        },
    )

    unsafe_generated = (
        "The signal was cleared and is no longer critical, "
        "so no action or approval is relevant."
    )

    answer = finalize_grounded_answer(
        request,
        unsafe_generated,
    )

    lower = answer.lower()

    assert (
        "no longer critical"
        not in lower
    )

    assert (
        "severity critical"
        in lower
    )

    assert (
        "0.032890885425"
        in answer
    )

    assert (
        "0.001920516347"
        in answer
    )

    assert (
        "17.13 times"
        in answer
    )

    assert (
        "action_required is false"
        in lower
    )

    assert (
        "does not mean the critical model signal "
        "did not exist"
        in lower
    )

    assert (
        "closed with resolution code model_cleared"
        in lower
    )

    assert (
        "must not be interpreted as retroactively "
        "invalidating"
        in lower
    )

    assert (
        "human approval remains required"
        in lower
    )

    assert (
        "automatic execution is not allowed"
        in lower
    )

    assert answer.count(disclosure) == 1


def test_build_human_approval_grounded_evidence():
    from operations.stage7o.explainer import (
        build_human_approval_grounded_evidence,
    )

    plan = {
        "evidence": [
            {
                "tool": "decision_cases",
                "read_only": True,
                "data": {
                    "items": [
                        {
                            "case_id": "case-stockout",
                            "decision_type": "STOCKOUT",
                            "status": "CLOSED",
                            "severity": "CRITICAL",
                            "action_required": False,
                            "approval_required": True,
                            "auto_execution_allowed": False,
                            "resolution_code": "MODEL_CLEARED",
                            "supplier_selected": None,
                            "automatic_po_allowed": None,
                        },
                        {
                            "case_id": "case-reorder",
                            "decision_type": "REORDER",
                            "status": "APPROVED_DRAFT",
                            "severity": "WATCH",
                            "action_required": True,
                            "recommended_units": 65,
                            "approval_required": True,
                            "auto_execution_allowed": False,
                            "draft_status": "APPROVED",
                            "supplier_selected": False,
                            "automatic_po_allowed": False,
                            "approved_by": "manager",
                        },
                    ]
                },
            }
        ]
    }

    grounded = (
        build_human_approval_grounded_evidence(
            plan
        )
    )

    assert len(grounded) == 2

    item = grounded[-1]

    assert (
        item["tool"]
        == "deterministic_human_approval_summary"
    )
    assert item["read_only"] is True

    data = item["data"]

    assert data["returned_case_count"] == 2
    assert (
        data["approval_required_case_count"]
        == 2
    )

    assert (
        data["decision_types_requiring_approval"]
        == ["REORDER", "STOCKOUT"]
    )

    assert data["assistant_can_approve"] is False
    assert (
        data["assistant_can_select_supplier"]
        is False
    )
    assert (
        data["assistant_can_create_purchase_order"]
        is False
    )
    assert (
        data["assistant_can_execute_procurement"]
        is False
    )

    reorder = next(
        item
        for item in data["cases"]
        if item["decision_type"] == "REORDER"
    )

    assert reorder["status"] == "APPROVED_DRAFT"
    assert reorder["draft_status"] == "APPROVED"
    assert reorder["supplier_selected"] is False
    assert (
        reorder["automatic_po_allowed"]
        is False
    )

    assert (
        "does not mean a purchase order was "
        "automatically created or executed"
        in data["interpretation"]
    )


def test_finalize_human_approval_blocks_assistant_action_claims():
    from operations.stage7o.llm import (
        GroundedLLMRequest,
        finalize_grounded_answer,
    )

    disclosure = (
        "Operational evidence is SYNTHETIC_CALIBRATED "
        "and must not be described as live or real "
        "pharmacy operations."
    )

    request = GroundedLLMRequest(
        question=(
            "What actions require human approval?"
        ),
        evidence=[
            {
                "tool": (
                    "deterministic_human_approval_summary"
                ),
                "read_only": True,
                "data": {
                    "returned_case_count": 2,
                    "approval_required_case_count": 2,
                    "decision_types_requiring_approval": [
                        "REORDER",
                        "STOCKOUT",
                    ],
                    "cases": [
                        {
                            "decision_type": "STOCKOUT",
                            "status": "CLOSED",
                            "approval_required": True,
                        },
                        {
                            "decision_type": "REORDER",
                            "status": "APPROVED_DRAFT",
                            "recommended_units": 65,
                            "approval_required": True,
                            "supplier_selected": False,
                            "automatic_po_allowed": False,
                        },
                    ],
                    "assistant_can_approve": False,
                    "assistant_can_select_supplier": False,
                    "assistant_can_create_purchase_order": False,
                    "assistant_can_execute_procurement": False,
                },
            }
        ],
        data_context={
            "contains_synthetic_operational_data": True,
            "safe_to_describe_as_live_operational": False,
            "assistant_disclosure_required": True,
            "disclosure": disclosure,
        },
        governance={
            "direct_database_access": False,
            "assistant_mutations_allowed": False,
            "automatic_supplier_selection": False,
            "automatic_purchase_order_creation": False,
            "procurement_execution_allowed": False,
        },
    )

    unsafe_generated = (
        "I can approve the REORDER draft, select a supplier, "
        "and create the purchase order automatically."
    )

    answer = finalize_grounded_answer(
        request,
        unsafe_generated,
    )

    lower = answer.lower()

    assert "i can approve" not in lower
    assert "create the purchase order automatically" not in lower

    assert "reorder" in lower
    assert "stockout" in lower

    assert "approved_draft" in lower
    assert "65 units" in lower

    assert (
        "does not mean a purchase order was "
        "automatically created or executed"
        in lower
    )

    assert (
        "assistant cannot approve decision cases"
        in lower
    )

    assert (
        "assistant cannot select suppliers"
        in lower
    )

    assert (
        "assistant cannot create purchase orders"
        in lower
    )

    assert (
        "assistant cannot execute procurement"
        in lower
    )

    assert (
        "sensitive workflow actions remain under "
        "human control"
        in lower
    )

    assert answer.count(disclosure) == 1


def test_build_approved_drafts_grounded_evidence():
    from operations.stage7o.explainer import (
        build_approved_drafts_grounded_evidence,
    )

    plan = {
        "evidence": [
            {
                "tool": "decision_cases",
                "read_only": True,
                "data": {
                    "items": [
                        {
                            "case_id": "case-reorder",
                            "decision_type": "REORDER",
                            "status": "APPROVED_DRAFT",
                            "branch_id": "branch-1",
                            "branch_code": "BR-001",
                            "branch_name": "Synthetic Branch",
                            "product_id": "product-1",
                            "trade_name_en": "Test Product",
                            "scientific_name": "Ingredient",
                            "severity": "WATCH",
                            "recommended_units": 65,
                            "approval_required": True,
                            "draft_id": "draft-1",
                            "draft_status": "APPROVED",
                            "approved_by": "manager",
                            "approved_at": "2026-09-01T22:07:31+00:00",
                            "supplier_selected": False,
                            "automatic_po_allowed": False,
                            "auto_execution_allowed": False,
                        },
                        {
                            "case_id": "case-stockout",
                            "decision_type": "STOCKOUT",
                            "status": "CLOSED",
                            "approval_required": True,
                        },
                    ]
                },
            }
        ]
    }

    grounded = build_approved_drafts_grounded_evidence(
        plan
    )

    assert len(grounded) == 2

    summary_item = grounded[-1]

    assert (
        summary_item["tool"]
        == "deterministic_approved_drafts_summary"
    )
    assert summary_item["read_only"] is True

    data = summary_item["data"]

    assert (
        data["returned_approved_draft_count"]
        == 1
    )

    drafts = data["approved_drafts"]

    assert len(drafts) == 1

    draft = drafts[0]

    assert draft["decision_type"] if False else True
    assert draft["recommended_units"] == 65
    assert draft["draft_status"] == "APPROVED"
    assert draft["supplier_selected"] is False
    assert (
        draft["automatic_po_allowed"]
        is False
    )
    assert (
        draft["auto_execution_allowed"]
        is False
    )

    assert (
        data["approved_draft_means_purchase_order"]
        is False
    )
    assert (
        data["assistant_can_select_supplier"]
        is False
    )
    assert (
        data["assistant_can_create_purchase_order"]
        is False
    )
    assert (
        data["assistant_can_execute_procurement"]
        is False
    )

    assert (
        "does not establish supplier selection"
        in data["interpretation"]
    )


def test_finalize_approved_drafts_blocks_procurement_claims():
    from operations.stage7o.llm import (
        GroundedLLMRequest,
        finalize_grounded_answer,
    )

    disclosure = (
        "Operational evidence is SYNTHETIC_CALIBRATED "
        "and must not be described as live or real "
        "pharmacy operations."
    )

    request = GroundedLLMRequest(
        question="Show approved replenishment drafts.",
        evidence=[
            {
                "tool":
                    "deterministic_approved_drafts_summary",
                "read_only": True,
                "data": {
                    "returned_approved_draft_count": 1,
                    "approved_drafts": [
                        {
                            "branch_code": "BR-001",
                            "branch_name": "Synthetic Branch",
                            "product_id": "product-1",
                            "trade_name_en": "Test Product",
                            "severity": "WATCH",
                            "recommended_units": 65,
                            "approval_required": True,
                            "draft_status": "APPROVED",
                            "approved_by": "manager",
                            "supplier_selected": False,
                            "automatic_po_allowed": False,
                            "auto_execution_allowed": False,
                        }
                    ],
                    "approved_draft_means_purchase_order":
                        False,
                    "assistant_can_select_supplier":
                        False,
                    "assistant_can_create_purchase_order":
                        False,
                    "assistant_can_execute_procurement":
                        False,
                },
            }
        ],
        data_context={
            "contains_synthetic_operational_data": True,
            "safe_to_describe_as_live_operational": False,
            "assistant_disclosure_required": True,
            "disclosure": disclosure,
        },
        governance={
            "direct_database_access": False,
            "assistant_mutations_allowed": False,
            "automatic_supplier_selection": False,
            "automatic_purchase_order_creation": False,
            "procurement_execution_allowed": False,
        },
    )

    unsafe_generated = (
        "The supplier was selected and the purchase "
        "order was created automatically."
    )

    answer = finalize_grounded_answer(
        request,
        unsafe_generated,
    )

    lower = answer.lower()

    assert "supplier was selected" not in lower
    assert (
        "purchase order was created automatically"
        not in lower
    )

    assert (
        "1 approved replenishment draft"
        in lower
    )

    assert "65 units" in lower
    assert "br-001" in lower
    assert "test product" in lower

    assert (
        "approved_draft means a governed "
        "human-approved replenishment draft exists"
        in lower
    )

    assert (
        "does not establish supplier selection"
        in lower
    )

    assert (
        "cannot select suppliers"
        in lower
    )

    assert (
        "cannot select suppliers, create purchase "
        "orders, or execute procurement"
        in lower
    )

    assert answer.count(disclosure) == 1


def test_stage7o_audit_metadata_is_privacy_minimized(
    monkeypatch,
):
    import json

    from operations.stage7o import api as stage7o_api

    captured: list[str] = []

    class FakeLogger:
        def info(self, message, payload):
            captured.append(
                message % payload
            )

        def exception(self, *args, **kwargs):
            raise AssertionError(
                "Audit helper must not fail"
            )

    monkeypatch.setattr(
        stage7o_api,
        "_AUDIT_LOGGER",
        FakeLogger(),
    )

    stage7o_api._write_assistant_audit(
        request_id="req-123",
        intent="DEMAND_CHANGE",
        status="OK",
        error_type=None,
        provider="DETERMINISTIC",
        model="CANONICAL_GROUNDED",
        tool_call_count=1,
        latency_ms=42.1256,
        operational_context="SYNTHETIC_OPERATIONAL",
        reference_context="PUBLIC_MARKET_EGYPT",
        synthetic_operational=True,
        read_only=True,
    )

    assert len(captured) == 1

    prefix = "STAGE7O_AUDIT "
    assert captured[0].startswith(prefix)

    payload = json.loads(
        captured[0][len(prefix):]
    )

    assert payload == {
        "event":
            "stage7o_assistant_request",
        "request_id":
            "req-123",
        "intent":
            "DEMAND_CHANGE",
        "status":
            "OK",
        "error_type":
            None,
        "provider":
            "DETERMINISTIC",
        "model":
            "CANONICAL_GROUNDED",
        "tool_call_count":
            1,
        "latency_ms":
            42.126,
        "operational_context":
            "SYNTHETIC_OPERATIONAL",
        "reference_context":
            "PUBLIC_MARKET_EGYPT",
        "synthetic_operational":
            True,
        "read_only":
            True,
    }

    forbidden_keys = {
        "question",
        "answer",
        "branch_id",
        "product_id",
        "evidence",
        "api_key",
        "authorization",
        "chain_of_thought",
        "reasoning",
    }

    assert forbidden_keys.isdisjoint(
        payload.keys()
    )

    serialized = json.dumps(
        payload,
        sort_keys=True,
    ).lower()

    assert "secret" not in serialized
    assert "branch-123" not in serialized
    assert "product-123" not in serialized

