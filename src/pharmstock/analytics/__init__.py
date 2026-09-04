"""Analytics-layer contracts used by Spark and later warehouse stages.

The package root is intentionally dependency-light. Spark imports submodules under
``pharmstock.analytics`` inside a minimal Python runtime that does not install the
application's Pydantic/domain stack. Silver validation helpers are therefore loaded
lazily only when application-side code explicitly asks for them.
"""

from typing import Any

from pharmstock.analytics.bronze import (
    BRONZE_EVENT_TOPICS,
    BRONZE_TOPICS,
    BronzeEnvelopeValidation,
    validate_bronze_envelope,
)
from pharmstock.analytics.silver_contracts import SILVER_TABLE_BY_EVENT

_LAZY_SILVER_EXPORTS = {
    "SilverEventValidation",
    "semantic_event_hash",
    "semantic_projection",
    "silver_table_for_event_type",
    "validate_silver_event",
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_SILVER_EXPORTS:
        from pharmstock.analytics import silver

        return getattr(silver, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BRONZE_EVENT_TOPICS",
    "BRONZE_TOPICS",
    "SILVER_TABLE_BY_EVENT",
    "BronzeEnvelopeValidation",
    "SilverEventValidation",
    "semantic_event_hash",
    "semantic_projection",
    "silver_table_for_event_type",
    "validate_bronze_envelope",
    "validate_silver_event",
]
