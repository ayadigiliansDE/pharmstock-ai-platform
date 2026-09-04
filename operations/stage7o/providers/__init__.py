"""Stage 7O external and local LLM provider adapters."""

from operations.stage7o.providers.ollama import (
    OllamaProvider,
)
from operations.stage7o.providers.openai import (
    OpenAIResponsesProvider,
)

__all__ = [
    "OllamaProvider",
    "OpenAIResponsesProvider",
]
