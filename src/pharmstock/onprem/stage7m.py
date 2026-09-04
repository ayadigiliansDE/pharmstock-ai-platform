"""Stage 7M operational decision API and workbench contracts."""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from typing import Final

STAGE7M_VERSION: Final[str] = "0.37.0"
DEFAULT_PORT: Final[int] = 8091
DEFAULT_HEARTBEAT_MAX_AGE_SECONDS: Final[int] = 60

ROLES: Final[tuple[str, ...]] = ("viewer", "operator", "manager", "admin")
ACTIONS: Final[tuple[str, ...]] = ("acknowledge", "approve-draft", "reject", "close")
ACTION_ROLES: Final[dict[str, frozenset[str]]] = {
    "acknowledge": frozenset({"operator", "manager", "admin"}),
    "close": frozenset({"operator", "manager", "admin"}),
    "reject": frozenset({"manager", "admin"}),
    "approve-draft": frozenset({"manager", "admin"}),
}


@dataclass(frozen=True, slots=True)
class Principal:
    actor_id: str
    role: str


def _configured_keys() -> tuple[tuple[str, Principal], ...]:
    return (
        (
            os.getenv("PHARMSTOCK_STAGE7M_VIEWER_KEY", "stage7m-local-viewer"),
            Principal("local-viewer", "viewer"),
        ),
        (
            os.getenv("PHARMSTOCK_STAGE7M_OPERATOR_KEY", "stage7m-local-operator"),
            Principal("local-operator", "operator"),
        ),
        (
            os.getenv("PHARMSTOCK_STAGE7M_MANAGER_KEY", "stage7m-local-manager"),
            Principal("local-manager", "manager"),
        ),
        (
            os.getenv("PHARMSTOCK_STAGE7M_ADMIN_KEY", "stage7m-local-admin"),
            Principal("local-admin", "admin"),
        ),
    )


def authenticate_api_key(api_key: str) -> Principal | None:
    candidate = api_key.strip()
    if not candidate:
        return None
    for configured, principal in _configured_keys():
        if configured and hmac.compare_digest(candidate, configured):
            return principal
    return None


def action_allowed(role: str, action: str) -> bool:
    normalized_role = role.strip().lower()
    normalized_action = action.strip().lower().replace("_", "-")
    return normalized_role in ACTION_ROLES.get(normalized_action, frozenset())


def stage7m_contract() -> dict[str, object]:
    return {
        "stage": "7M",
        "version": STAGE7M_VERSION,
        "runtime": "OPERATIONAL_DECISION_API_AND_WORKBENCH",
        "http": {
            "bind": "127.0.0.1",
            "port": DEFAULT_PORT,
            "authentication": "API_KEY_RBAC_LOCAL_BOUNDARY",
            "authorization": "DENY_BY_DEFAULT",
        },
        "roles": list(ROLES),
        "actions": {action: sorted(roles) for action, roles in ACTION_ROLES.items()},
        "governance": {
            "human_approval_required": True,
            "automatic_purchase_order_creation": False,
            "automatic_supplier_selection": False,
            "purchase_order_endpoint_exists": False,
            "database_role_has_procurement_write": False,
            "audit_updates_allowed": False,
            "audit_deletes_allowed": False,
        },
        "serving": {
            "case_queue_view": "decision_ops.v_case_workbench",
            "summary_endpoint": "/v1/metrics/summary",
            "workbench": "/workbench",
        },
        "cloud_mutation": False,
        "bigquery_write": False,
    }
