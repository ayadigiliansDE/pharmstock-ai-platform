"""Local Ollama provider for Stage 7O.

This provider:
- runs locally,
- requires no paid API,
- receives governed evidence only,
- exposes no Stage7M tools,
- performs no mutations,
- strips leaked model reasoning before returning an answer.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlparse

import httpx

from operations.stage7o.llm import (
    GroundedLLMRequest,
    LLMAnswer,
    LLMProviderError,
    build_provider_payload,
    finalize_grounded_answer,
)


DEFAULT_OLLAMA_BASE_URL = (
    "http://host.docker.internal:11434"
)

DEFAULT_OLLAMA_MODEL = "qwen3:4b"

DEFAULT_TIMEOUT_SECONDS = 120.0


def _validate_local_ollama_url(
    base_url: str,
) -> str:
    normalized = base_url.strip().rstrip("/")

    parsed = urlparse(normalized)

    allowed_hosts = {
        "127.0.0.1",
        "localhost",
        "host.docker.internal",
    }

    if parsed.scheme != "http":
        raise LLMProviderError(
            "Ollama endpoint must use local HTTP"
        )

    if parsed.hostname not in allowed_hosts:
        raise LLMProviderError(
            "Ollama endpoint must remain local"
        )

    if parsed.port not in (None, 11434):
        raise LLMProviderError(
            "Unexpected Ollama port"
        )

    return normalized


def _sanitize_ollama_response(
    text: str,
) -> str:
    cleaned = text.strip()

    if not cleaned:
        raise LLMProviderError(
            "Ollama returned an empty response"
        )

    # Some Qwen/Ollama combinations leak the reasoning
    # into response even when think=false.
    #
    # Keep only content after the final </think>.
    if "</think>" in cleaned:
        cleaned = cleaned.rsplit(
            "</think>",
            1,
        )[-1].strip()

    # Defensive handling for a complete <think> block.
    while (
        "<think>" in cleaned
        and "</think>" in cleaned
    ):
        before, remainder = cleaned.split(
            "<think>",
            1,
        )

        _, after = remainder.split(
            "</think>",
            1,
        )

        cleaned = (
            before + after
        ).strip()

    if (
        "<think>" in cleaned
        or "</think>" in cleaned
    ):
        raise LLMProviderError(
            "Ollama response contains unresolved "
            "reasoning markers"
        )

    if not cleaned:
        raise LLMProviderError(
            "Ollama returned no final answer "
            "after reasoning sanitation"
        )

    return cleaned


def _apply_required_disclosure(
    text: str,
    data_context: dict[str, Any],
) -> str:
    final_text = text.strip()

    if (
        data_context.get(
            "assistant_disclosure_required"
        )
        is not True
    ):
        return final_text

    disclosure = data_context.get(
        "disclosure"
    )

    if (
        not isinstance(disclosure, str)
        or not disclosure.strip()
    ):
        raise LLMProviderError(
            "Required provenance disclosure "
            "is missing"
        )

    disclosure = disclosure.strip()

    if disclosure in final_text:
        return final_text

    return (
        f"{disclosure}\n\n"
        f"{final_text}"
    )


class OllamaProvider:
    """Local generation-only Ollama adapter."""

    name = "OLLAMA_LOCAL"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float = (
            DEFAULT_TIMEOUT_SECONDS
        ),
        client: httpx.AsyncClient | None = None,
    ) -> None:
        configured_url = (
            base_url
            or os.getenv(
                "PHARMSTOCK_STAGE7O_OLLAMA_BASE_URL"
            )
            or DEFAULT_OLLAMA_BASE_URL
        )

        self.base_url = (
            _validate_local_ollama_url(
                configured_url
            )
        )

        self.model = (
            model
            or os.getenv(
                "PHARMSTOCK_STAGE7O_OLLAMA_MODEL"
            )
            or DEFAULT_OLLAMA_MODEL
        ).strip()

        if not self.model:
            raise LLMProviderError(
                "Ollama model must not be blank"
            )

        self.timeout_seconds = float(
            timeout_seconds
        )

        self._client = client

    async def generate(
        self,
        request: GroundedLLMRequest,
    ) -> LLMAnswer:
        governed = build_provider_payload(
            request
        )

        policy = "\n".join(
            f"- {rule}"
            for rule in governed["policy"]
        )

        evidence_payload = {
            "question":
                governed["question"],
            "data_context":
                governed["data_context"],
            "governance":
                governed["governance"],
            "evidence":
                governed["evidence"],
        }

        prompt = (
            "You are the governed PharmStock AI "
            "assistant.\n\n"
            "MANDATORY POLICY:\n"
            f"{policy}\n\n"
            "Return only the final user-facing "
            "answer. Do not include reasoning, "
            "chain-of-thought, <think> tags, "
            "or hidden analysis.\n\n"
            "GOVERNED EVIDENCE PACKAGE:\n"
            + json.dumps(
                evidence_payload,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )
        )

        api_payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "think": False,
        }

        owns_client = (
            self._client is None
        )

        client = (
            self._client
            or httpx.AsyncClient(
                timeout=self.timeout_seconds
            )
        )

        try:
            try:
                response = await client.post(
                    (
                        f"{self.base_url}"
                        "/api/generate"
                    ),
                    json=api_payload,
                )
            except httpx.HTTPError as exc:
                raise LLMProviderError(
                    "Local Ollama request failed"
                ) from exc

            if response.status_code >= 400:
                raise LLMProviderError(
                    "Ollama returned HTTP "
                    f"{response.status_code}"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise LLMProviderError(
                    "Ollama returned invalid JSON"
                ) from exc

            if not isinstance(
                payload,
                dict,
            ):
                raise LLMProviderError(
                    "Ollama returned an invalid "
                    "response object"
                )

            if payload.get("done") is not True:
                raise LLMProviderError(
                    "Ollama response did not "
                    "complete"
                )

            raw_text = payload.get(
                "response"
            )

            if not isinstance(
                raw_text,
                str,
            ):
                raise LLMProviderError(
                    "Ollama response text "
                    "is missing"
                )

            clean_text = (
                _sanitize_ollama_response(
                    raw_text
                )
            )

            final_text = (
                finalize_grounded_answer(
                    request,
                    clean_text,
                )
            )

            returned_model = payload.get(
                "model"
            )

            return LLMAnswer(
                text=final_text,
                provider=self.name,
                model=(
                    returned_model
                    if isinstance(
                        returned_model,
                        str,
                    )
                    else self.model
                ),
            )

        finally:
            if owns_client:
                await client.aclose()
