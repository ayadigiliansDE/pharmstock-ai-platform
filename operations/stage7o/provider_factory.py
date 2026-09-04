"""Fail-closed Stage 7O LLM provider factory."""

from __future__ import annotations

import os
from typing import Any

from operations.stage7o.llm import (
    LLMProvider,
    LLMProviderError,
    NotConfiguredLLMProvider,
)
from operations.stage7o.providers.ollama import (
    OllamaProvider,
)
from operations.stage7o.providers.openai import (
    OpenAIResponsesProvider,
)


PROVIDER_ENV = "PHARMSTOCK_STAGE7O_LLM_PROVIDER"
OPENAI_API_KEY_ENV = "PHARMSTOCK_STAGE7O_OPENAI_API_KEY"
OPENAI_MODEL_ENV = "PHARMSTOCK_STAGE7O_OPENAI_MODEL"

OLLAMA_BASE_URL_ENV = "PHARMSTOCK_STAGE7O_OLLAMA_BASE_URL"
OLLAMA_MODEL_ENV = "PHARMSTOCK_STAGE7O_OLLAMA_MODEL"

DEFAULT_PROVIDER = "none"


def configured_provider_name() -> str:
    value = os.getenv(
        PROVIDER_ENV,
        DEFAULT_PROVIDER,
    )

    return value.strip().lower()


def build_llm_provider() -> LLMProvider:
    provider_name = configured_provider_name()

    if provider_name in {
        "",
        "none",
        "not_configured",
    }:
        return NotConfiguredLLMProvider()

    if provider_name == "openai":
        api_key = os.getenv(
            OPENAI_API_KEY_ENV,
            "",
        ).strip()

        if not api_key:
            raise LLMProviderError(
                "Stage7O LLM provider is configured as "
                "openai but the OpenAI API key is missing"
            )

        model = os.getenv(
            OPENAI_MODEL_ENV,
            "",
        ).strip()

        return OpenAIResponsesProvider(
            api_key=api_key,
            model=model or None,
        )

    if provider_name == "ollama":
        base_url = os.getenv(
            OLLAMA_BASE_URL_ENV,
            "",
        ).strip()

        model = os.getenv(
            OLLAMA_MODEL_ENV,
            "",
        ).strip()

        return OllamaProvider(
            base_url=base_url or None,
            model=model or None,
        )

    raise LLMProviderError(
        "Unsupported Stage7O LLM provider: "
        f"{provider_name}"
    )


def provider_runtime_metadata(
    provider: LLMProvider,
) -> dict[str, Any]:
    provider_name = getattr(
        provider,
        "name",
        "UNKNOWN",
    )

    model = getattr(
        provider,
        "model",
        None,
    )

    return {
        "configured_selection":
            configured_provider_name(),
        "provider": provider_name,
        "model": model,
        "configured":
            provider_name != "NOT_CONFIGURED",
        "api_key_present": bool(
            os.getenv(
                OPENAI_API_KEY_ENV,
                "",
            ).strip()
        )
        if provider_name == "OPENAI_RESPONSES"
        else False,
    }
