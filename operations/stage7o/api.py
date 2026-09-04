"""Stage 7O standalone AI assistant API."""

from __future__ import annotations

import json
import logging
import time
import uuid

from pathlib import Path

from contextlib import asynccontextmanager
from typing import AsyncIterator

from pydantic import BaseModel, Field

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse

from pharmstock.onprem.stage7o import STAGE7O_VERSION, stage7o_contract

from .client import Stage7MClient, Stage7MClientError
from .explainer import (
    EvidenceExplanationError,
    build_approved_drafts_grounded_evidence,
    build_critical_stockout_grounded_evidence,
    build_demand_trend_grounded_evidence,
    build_human_approval_grounded_evidence,
    build_reorder_grounded_evidence,
    build_stockout_ranking_grounded_evidence,
    build_supplier_lead_time_grounded_evidence,
)
from .llm import (
    GroundedLLMRequest,
    LLMProviderError,
)
from .orchestrator import (
    AssistantOrchestrationError,
    execute_plan,
)
from .router import (
    AssistantIntent,
    AssistantRoutingError,
    route_question,
)
from .provider_factory import (
    build_llm_provider,
    provider_runtime_metadata,
)


_AUDIT_LOGGER = logging.getLogger("uvicorn.error")


def _write_assistant_audit(
    *,
    request_id: str,
    intent: str | None,
    status: str,
    error_type: str | None,
    provider: str | None,
    model: str | None,
    tool_call_count: int | None,
    latency_ms: float,
    operational_context: str | None,
    reference_context: str | None,
    synthetic_operational: bool | None,
    read_only: bool = True,
) -> None:
    """
    Emit privacy-minimized Stage 7O assistant audit metadata.

    Deliberately excluded:
    - user question
    - generated answer
    - branch/product identifiers
    - evidence payloads
    - API keys or credentials
    - chain-of-thought / hidden reasoning

    Audit failure must never affect assistant availability.
    """
    try:
        record = {
            "event": "stage7o_assistant_request",
            "request_id": request_id,
            "intent": intent,
            "status": status,
            "error_type": error_type,
            "provider": provider,
            "model": model,
            "tool_call_count": tool_call_count,
            "latency_ms": round(
                max(float(latency_ms), 0.0),
                3,
            ),
            "operational_context": operational_context,
            "reference_context": reference_context,
            "synthetic_operational": synthetic_operational,
            "read_only": bool(read_only),
        }

        _AUDIT_LOGGER.info(
            "STAGE7O_AUDIT %s",
            json.dumps(
                record,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ),
        )

    except Exception:
        # Audit telemetry is intentionally fail-open.
        # It must never change governed assistant behavior.
        _AUDIT_LOGGER.exception(
            "STAGE7O_AUDIT_WRITE_FAILED"
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    client = Stage7MClient()
    llm_provider = build_llm_provider()

    app.state.stage7m_client = client
    app.state.llm_provider = llm_provider

    try:
        yield
    finally:
        await client.close()


app = FastAPI(
    title="PharmStock AI Assistant",
    version=STAGE7O_VERSION,
    lifespan=lifespan,
)



@app.get("/", include_in_schema=False)
def stage7o_ui():
    ui_path = (
        Path(__file__).resolve().parent
        / "static"
        / "index.html"
    )

    if not ui_path.exists():
        raise HTTPException(
            status_code=503,
            detail="Stage 7O UI is unavailable.",
        )

    return FileResponse(
        ui_path,
        media_type="text/html; charset=utf-8",
    )


@app.get("/health")
async def health(request: Request) -> JSONResponse:
    client: Stage7MClient = request.app.state.stage7m_client

    try:
        upstream = await client.health()
    except Stage7MClientError as exc:
        return JSONResponse(
            status_code=503,
            content={
                "status": "UNHEALTHY",
                "stage": "7O",
                "version": STAGE7O_VERSION,
                "stage7m": {
                    "healthy": False,
                    "error": str(exc),
                },
                "direct_database_access": False,
                "automatic_supplier_selection": False,
                "automatic_purchase_order_creation": False,
            },
        )

    upstream_safe = (
        upstream.get("status") == "HEALTHY"
        and upstream.get("procurement_write_blocked") is True
        and upstream.get("automatic_po_creation") is False
    )

    payload = {
        "status": "HEALTHY" if upstream_safe else "UNHEALTHY",
        "stage": "7O",
        "version": STAGE7O_VERSION,
        "stage7m": {
            "healthy": upstream_safe,
            "status": upstream.get("status"),
            "version": upstream.get("version"),
        },
        "direct_database_access": False,
        "automatic_supplier_selection": False,
        "automatic_purchase_order_creation": False,
    }

    return JSONResponse(
        status_code=200 if upstream_safe else 503,
        content=payload,
    )


@app.get("/v1/meta")
async def meta(request: Request) -> dict[str, object]:
    client: Stage7MClient = request.app.state.stage7m_client
    llm_provider = request.app.state.llm_provider

    return {
        **stage7o_contract(),
        "stage7m_api_key_configured": client.api_key_configured,
        "llm_runtime": provider_runtime_metadata(
            llm_provider
        ),
    }


class AssistantAskRequest(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=2000,
    )
    branch_id: str | None = None
    product_id: str | None = None


@app.post("/v1/assistant/ask")
async def assistant_ask(
    payload: AssistantAskRequest,
    request: Request,
) -> JSONResponse:
    client: Stage7MClient = (
        request.app.state.stage7m_client
    )
    llm_provider = (
        request.app.state.llm_provider
    )

    request_id = str(uuid.uuid4())
    started_at = time.perf_counter()

    audit_intent: str | None = None
    audit_provider: str | None = None
    audit_model: str | None = None
    audit_tool_call_count: int | None = None
    audit_operational_context: str | None = None
    audit_reference_context: str | None = None
    audit_synthetic_operational: bool | None = None

    try:
        route = route_question(
            payload.question,
            branch_id=payload.branch_id,
            product_id=payload.product_id,
        )

        audit_intent = route.intent.value

        plan = await execute_plan(
            client,
            question=payload.question,
            calls=route.calls,
        )

        evidence = plan["evidence"]

        audit_tool_call_count = plan.get(
            "tool_call_count"
        )

        data_context = plan.get(
            "data_context",
            {},
        )

        if isinstance(data_context, dict):
            audit_operational_context = (
                data_context.get(
                    "operational_context"
                )
            )
            audit_reference_context = (
                data_context.get(
                    "reference_context"
                )
            )
            audit_synthetic_operational = bool(
                data_context.get(
                    "contains_synthetic_operational_data",
                    False,
                )
            )

        if (
            route.intent
            == AssistantIntent.REORDER_EXPLANATION
        ):
            evidence = (
                build_reorder_grounded_evidence(
                    plan
                )
            )

        elif (
            route.intent
            == AssistantIntent.HIGHEST_STOCKOUT_RISK
        ):
            evidence = (
                build_stockout_ranking_grounded_evidence(
                    plan
                )
            )

        elif (
            route.intent
            == AssistantIntent.WORST_SUPPLIER_LEAD_TIME
        ):
            evidence = (
                build_supplier_lead_time_grounded_evidence(
                    plan
                )
            )

        elif (
            route.intent
            == AssistantIntent.DEMAND_CHANGE
        ):
            evidence = (
                build_demand_trend_grounded_evidence(
                    plan
                )
            )

        elif (
            route.intent
            == AssistantIntent.CRITICAL_STOCKOUT_SIGNAL
        ):
            evidence = (
                build_critical_stockout_grounded_evidence(
                    plan
                )
            )

        elif (
            route.intent
            == AssistantIntent.APPROVED_REPLENISHMENT_DRAFTS
        ):
            evidence = (
                build_approved_drafts_grounded_evidence(
                    plan
                )
            )

        elif (
            route.intent
            == AssistantIntent.HUMAN_APPROVAL_ACTIONS
        ):
            evidence = (
                build_human_approval_grounded_evidence(
                    plan
                )
            )

        llm_request = GroundedLLMRequest(
            question=plan["question"],
            evidence=evidence,
            data_context=plan["data_context"],
            governance=plan["governance"],
        )

        deterministic_intents = {
            AssistantIntent.HIGHEST_STOCKOUT_RISK,
            AssistantIntent.REORDER_EXPLANATION,
            AssistantIntent.APPROVED_REPLENISHMENT_DRAFTS,
            AssistantIntent.WORST_SUPPLIER_LEAD_TIME,
            AssistantIntent.DEMAND_CHANGE,
            AssistantIntent.CRITICAL_STOCKOUT_SIGNAL,
            AssistantIntent.HUMAN_APPROVAL_ACTIONS,
        }

        if route.intent in deterministic_intents:
            from .llm import finalize_grounded_answer

            answer_text = finalize_grounded_answer(
                llm_request,
                "DETERMINISTIC_GROUNDED_RESPONSE",
            )
            provider_name = "DETERMINISTIC"
            model_name = "CANONICAL_GROUNDED"
        else:
            answer = await llm_provider.generate(
                llm_request
            )
            answer_text = answer.text
            provider_name = answer.provider
            model_name = answer.model

        audit_provider = provider_name
        audit_model = model_name

    except AssistantRoutingError as exc:
        _write_assistant_audit(
            request_id=request_id,
            intent=audit_intent,
            status="REJECTED",
            error_type="ROUTING_ERROR",
            provider=audit_provider,
            model=audit_model,
            tool_call_count=audit_tool_call_count,
            latency_ms=(
                time.perf_counter()
                - started_at
            ) * 1000.0,
            operational_context=(
                audit_operational_context
            ),
            reference_context=(
                audit_reference_context
            ),
            synthetic_operational=(
                audit_synthetic_operational
            ),
            read_only=True,
        )

        return JSONResponse(
            status_code=422,
            content={
                "status": "REJECTED",
                "error_type": "ROUTING_ERROR",
                "detail": str(exc),
                "read_only": True,
            },
        )

    except (
        AssistantOrchestrationError,
        EvidenceExplanationError,
    ) as exc:
        _write_assistant_audit(
            request_id=request_id,
            intent=audit_intent,
            status="FAILED",
            error_type="GOVERNED_EVIDENCE_ERROR",
            provider=audit_provider,
            model=audit_model,
            tool_call_count=audit_tool_call_count,
            latency_ms=(
                time.perf_counter()
                - started_at
            ) * 1000.0,
            operational_context=(
                audit_operational_context
            ),
            reference_context=(
                audit_reference_context
            ),
            synthetic_operational=(
                audit_synthetic_operational
            ),
            read_only=True,
        )

        return JSONResponse(
            status_code=502,
            content={
                "status": "FAILED",
                "error_type": "GOVERNED_EVIDENCE_ERROR",
                "detail": str(exc),
                "read_only": True,
            },
        )

    except LLMProviderError as exc:
        _write_assistant_audit(
            request_id=request_id,
            intent=audit_intent,
            status="FAILED",
            error_type="LLM_PROVIDER_ERROR",
            provider=audit_provider,
            model=audit_model,
            tool_call_count=audit_tool_call_count,
            latency_ms=(
                time.perf_counter()
                - started_at
            ) * 1000.0,
            operational_context=(
                audit_operational_context
            ),
            reference_context=(
                audit_reference_context
            ),
            synthetic_operational=(
                audit_synthetic_operational
            ),
            read_only=True,
        )

        return JSONResponse(
            status_code=503,
            content={
                "status": "FAILED",
                "error_type": "LLM_PROVIDER_ERROR",
                "detail": str(exc),
                "read_only": True,
            },
        )

    _write_assistant_audit(
        request_id=request_id,
        intent=audit_intent,
        status="OK",
        error_type=None,
        provider=audit_provider,
        model=audit_model,
        tool_call_count=audit_tool_call_count,
        latency_ms=(
            time.perf_counter()
            - started_at
        ) * 1000.0,
        operational_context=(
            audit_operational_context
        ),
        reference_context=(
            audit_reference_context
        ),
        synthetic_operational=(
            audit_synthetic_operational
        ),
        read_only=True,
    )

    return JSONResponse(
        status_code=200,
        content={
            "status": "OK",
            "intent": route.intent.value,
            "answer": answer_text,
            "provider": provider_name,
            "model": model_name,
            "tool_call_count": (
                plan["tool_call_count"]
            ),
            "read_only": True,
            "data_context": (
                plan["data_context"]
            ),
            "governance": (
                plan["governance"]
            ),
        },
    )

