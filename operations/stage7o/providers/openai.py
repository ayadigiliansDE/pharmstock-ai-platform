"""OpenAI Responses API adapter for Stage 7O.

This adapter is deliberately generation-only.

It receives an already-governed evidence package after:
Stage7M -> Stage7O tools -> orchestrator -> provenance gate.

It has:
- no database access,
- no Stage7M tool execution,
- no mutation capability,
- no supplier selection,
- no purchase-order capability.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from operations.stage7o.llm import (
    GroundedLLMRequest,
    LLMAnswer,
    LLMProviderError,
    build_provider_payload,
)


OPENAI_RESPONSES_URL = (
    "https://api.openai.com/v1/responses"
)

DEFAULT_OPENAI_MODEL = "gpt-5.6-terra"

DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_OUTPUT_TOKENS = 1600


def _extract_output_text(
    response_payload: dict[str, Any],
) -> str:
    direct = response_payload.get("output_text")

    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    parts: list[str] = []

    output = response_payload.get("output")

    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue

            if item.get("type") != "message":
                continue

            content = item.get("content")

            if not isinstance(content, list):
                continue

            for part in content:
                if not isinstance(part, dict):
                    continue

                if part.get("type") != "output_text":
                    continue

                text = part.get("text")

                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())

    text = "\n".join(parts).strip()

    if not text:
        raise LLMProviderError(
            "OpenAI response contained no output text"
        )

    return text


def _apply_required_disclosure(
    text: str,
    data_context: dict[str, Any],
) -> str:
    if (
        data_context.get(
            "assistant_disclosure_required"
        )
        is not True
    ):
        return text.strip()

    disclosure = data_context.get("disclosure")

    if not isinstance(disclosure, str):
        raise LLMProviderError(
            "Required provenance disclosure is missing"
        )

    disclosure = disclosure.strip()

    if not disclosure:
        raise LLMProviderError(
            "Required provenance disclosure is missing"
        )

    # Do not trust the model alone to include the disclosure.
    # Stage7O adds the authoritative disclosure deterministically.
    if disclosure in text:
        return text.strip()

    return f"{disclosure}\n\n{text.strip()}"


class OpenAIResponsesProvider:
    """Generation-only adapter to the OpenAI Responses API."""

    name = "OPENAI_RESPONSES"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        endpoint: str = OPENAI_RESPONSES_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = (
            api_key
            or os.getenv(
                "PHARMSTOCK_STAGE7O_OPENAI_API_KEY"
            )
            or ""
        ).strip()

        self.model = (
            model
            or os.getenv(
                "PHARMSTOCK_STAGE7O_OPENAI_MODEL"
            )
            or DEFAULT_OPENAI_MODEL
        ).strip()

        self.endpoint = endpoint.strip()
        self.timeout_seconds = float(timeout_seconds)
        self.max_output_tokens = int(
            max_output_tokens
        )
        self._client = client

        if not self.model:
            raise LLMProviderError(
                "OpenAI model must not be blank"
            )

        if not self.endpoint.startswith("https://"):
            raise LLMProviderError(
                "OpenAI endpoint must use HTTPS"
            )

        if self.max_output_tokens < 1:
            raise LLMProviderError(
                "max_output_tokens must be positive"
            )

    async def generate(
        self,
        request: GroundedLLMRequest,
    ) -> LLMAnswer:
        if not self._api_key:
            raise LLMProviderError(
                "Stage7O OpenAI API key is not configured"
            )

        governed = build_provider_payload(request)

        instructions = "\n".join(
            f"- {rule}"
            for rule in governed["policy"]
        )

        # The model gets governed evidence only.
        # It never receives database credentials or tool handles.
        input_payload = {
            "question": governed["question"],
            "data_context": governed["data_context"],
            "governance": governed["governance"],
            "evidence": governed["evidence"],
        }

        api_payload = {
            "model": self.model,
            "instructions": instructions,
            "input": json.dumps(
                input_payload,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ),
            "store": False,
            "max_output_tokens":
                self.max_output_tokens,
            "text": {
                "verbosity": "low",
            },
            # No model-side tools are exposed.
            "tools": [],
            "parallel_tool_calls": False,
        }

        headers = {
            "Authorization":
                f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        owns_client = self._client is None

        client = self._client or httpx.AsyncClient(
            timeout=self.timeout_seconds
        )

        try:
            try:
                response = await client.post(
                    self.endpoint,
                    headers=headers,
                    json=api_payload,
                )
            except httpx.HTTPError as exc:
                raise LLMProviderError(
                    "OpenAI Responses API request failed"
                ) from exc

            if response.status_code >= 400:
                raise LLMProviderError(
                    "OpenAI Responses API returned "
                    f"HTTP {response.status_code}"
                )

            try:
                response_payload = response.json()
            except ValueError as exc:
                raise LLMProviderError(
                    "OpenAI Responses API returned "
                    "invalid JSON"
                ) from exc

            if not isinstance(
                response_payload,
                dict,
            ):
                raise LLMProviderError(
                    "OpenAI Responses API returned "
                    "an invalid response object"
                )

            status = response_payload.get("status")

            if status not in (None, "completed"):
                raise LLMProviderError(
                    "OpenAI response did not complete "
                    f"successfully: {status}"
                )

            generated_text = _extract_output_text(
                response_payload
            )

            final_text = _apply_required_disclosure(
                generated_text,
                request.data_context,
            )

            returned_model = response_payload.get(
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
