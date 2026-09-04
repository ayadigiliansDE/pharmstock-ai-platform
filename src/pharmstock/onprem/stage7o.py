"""Stage 7O standalone AI assistant contracts."""

from __future__ import annotations

from typing import Final

STAGE7O_VERSION: Final[str] = "0.39.0"
DEFAULT_PORT: Final[int] = 8092
DEFAULT_STAGE7M_BASE_URL: Final[str] = "http://stage7m-api:8091"


def stage7o_contract() -> dict[str, object]:
    return {
        "stage": "7O",
        "version": STAGE7O_VERSION,
        "runtime": "STANDALONE_AI_ASSISTANT",
        "http": {
            "bind": "127.0.0.1",
            "port": DEFAULT_PORT,
        },
        "architecture": {
            "ui": "VANILLA_HTML_CSS_JAVASCRIPT",
            "operational_data_boundary": "STAGE7M_HTTP_API_ONLY",
            "direct_database_access": False,
            "postgres_driver_present": False,
            "bigquery_direct_access": False,
            "vector_database_required": False,
        },
        "governance": {
            "human_approval_required": True,
            "assistant_mutations_allowed": False,
            "automatic_purchase_order_creation": False,
            "automatic_supplier_selection": False,
            "procurement_execution_allowed": False,
        },
        "upstream": {
            "service": "STAGE7M",
            "default_base_url": DEFAULT_STAGE7M_BASE_URL,
            "authentication": "SERVICE_TO_SERVICE_API_KEY",
            "methods": ["GET"],
        },
        "llm": {
            "provider_adapter": "NOT_CONFIGURED",
            "provider_required_for_health": False,
        },
        "cloud_mutation": False,
        "bigquery_write": False,
    }
