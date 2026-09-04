"""Contracts for the Stage 7E high-fidelity historical POS workload simulator.

Stage 7E writes only SYNTHETIC_CALIBRATED operational history. Product identities and
observed retail prices remain sourced from the Egyptian-market master loaded in Stage 7A.
The simulator deliberately keeps those truth boundaries separate.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Final

HISTORY_MODEL_VERSION: Final[str] = "EG_POS_HISTORY_V2_CUSTOMER_FAST_AUDIT"
HISTORY_PROVENANCE: Final[str] = "SYNTHETIC_CALIBRATED"
DEFAULT_END_DATE: Final[date] = date(2026, 8, 22)
DEFAULT_SEED: Final[int] = 20260823
CUSTOMERS_PER_BRANCH: Final[int] = 50
HOUSEHOLDS_PER_BRANCH: Final[int] = 20
PATIENTS_PER_HOUSEHOLD: Final[int] = 3


class HistoryProfile(StrEnum):
    """Local workload profiles with an explicit production-scale path."""

    DEV = "dev"
    ACCEPTANCE = "acceptance"
    PROD_LIKE = "prod_like"


@dataclass(frozen=True, slots=True)
class HistoryProfileConfig:
    profile: HistoryProfile
    branch_limit: int
    days: int
    base_transactions_per_branch_day: int
    min_sale_headers: int
    min_sale_lines: int
    expected_scale_label: str

    @property
    def start_date(self) -> date:
        return DEFAULT_END_DATE - timedelta(days=self.days - 1)


PROFILE_CONFIGS: Final[dict[HistoryProfile, HistoryProfileConfig]] = {
    HistoryProfile.DEV: HistoryProfileConfig(
        profile=HistoryProfile.DEV,
        branch_limit=27,
        days=3,
        base_transactions_per_branch_day=8,
        min_sale_headers=250,
        min_sale_lines=350,
        expected_scale_label="hundreds_of_transactions",
    ),
    HistoryProfile.ACCEPTANCE: HistoryProfileConfig(
        profile=HistoryProfile.ACCEPTANCE,
        branch_limit=5_000,
        days=14,
        base_transactions_per_branch_day=24,
        min_sale_headers=1_200_000,
        min_sale_lines=2_000_000,
        expected_scale_label="millions_of_operational_rows",
    ),
    HistoryProfile.PROD_LIKE: HistoryProfileConfig(
        profile=HistoryProfile.PROD_LIKE,
        branch_limit=5_000,
        days=365,
        base_transactions_per_branch_day=24,
        min_sale_headers=30_000_000,
        min_sale_lines=50_000_000,
        expected_scale_label="tens_of_millions_of_transactions",
    ),
}


@dataclass(frozen=True, slots=True)
class HistoryRunContract:
    profile: str
    seed: int
    start_date: str
    end_date: str
    branch_limit: int
    days: int
    base_transactions_per_branch_day: int
    min_sale_headers: int
    min_sale_lines: int
    expected_scale_label: str
    history_model_version: str = HISTORY_MODEL_VERSION
    provenance_class: str = HISTORY_PROVENANCE


def resolve_profile(
    profile: HistoryProfile,
    *,
    end_date: date = DEFAULT_END_DATE,
    days: int | None = None,
    branch_limit: int | None = None,
    base_transactions_per_branch_day: int | None = None,
    seed: int = DEFAULT_SEED,
) -> HistoryRunContract:
    """Resolve a deterministic run contract, allowing explicit local overrides."""

    base = PROFILE_CONFIGS[profile]
    resolved_days = base.days if days is None else days
    resolved_branches = base.branch_limit if branch_limit is None else branch_limit
    resolved_tx = (
        base.base_transactions_per_branch_day
        if base_transactions_per_branch_day is None
        else base_transactions_per_branch_day
    )
    if resolved_days <= 0:
        raise ValueError("days must be positive")
    if resolved_branches <= 0 or resolved_branches > 5_000:
        raise ValueError("branch_limit must be in [1, 5000]")
    if resolved_tx <= 0 or resolved_tx > 250:
        raise ValueError("base_transactions_per_branch_day must be in [1, 250]")
    start_date = end_date - timedelta(days=resolved_days - 1)
    scale = resolved_branches * resolved_days / (base.branch_limit * base.days)
    return HistoryRunContract(
        profile=profile.value,
        seed=seed,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        branch_limit=resolved_branches,
        days=resolved_days,
        base_transactions_per_branch_day=resolved_tx,
        min_sale_headers=max(
            1,
            int(
                base.min_sale_headers
                * scale
                * resolved_tx
                / base.base_transactions_per_branch_day
            ),
        ),
        min_sale_lines=max(
            1,
            int(
                base.min_sale_lines
                * scale
                * resolved_tx
                / base.base_transactions_per_branch_day
            ),
        ),
        expected_scale_label=base.expected_scale_label,
    )


def run_token(contract: HistoryRunContract) -> str:
    """Return a stable short token used inside deterministic transaction identifiers."""

    import hashlib

    canonical = json.dumps(asdict(contract), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def history_contract(contract: HistoryRunContract) -> dict[str, object]:
    """Serialize the production-like behavior and truth boundary of the simulator."""

    return {
        "stage": "7E",
        "role": "HIGH_FIDELITY_HISTORICAL_POS_AND_OPERATIONAL_SIMULATOR",
        "run": asdict(contract),
        "run_token": run_token(contract),
        "truth_boundary": {
            "product_identity": "PUBLIC_MARKET_EGYPT_FROM_STAGE7A",
            "retail_price": "PUBLIC_MARKET_EGYPT_FROM_STAGE7A",
            "branch_network": "SYNTHETIC_CALIBRATED_FROM_STAGE7B",
            "purchase_cost": "SYNTHETIC_CALIBRATED_FROM_STAGE7C",
            "pos_transactions": HISTORY_PROVENANCE,
            "inventory_history": HISTORY_PROVENANCE,
            "procurement_history": HISTORY_PROVENANCE,
            "customer_behavior": "SYNTHETIC_CALIBRATED_PRIVACY_SAFE",
            "customer_direct_identifiers": "NOT_GENERATED",
            "patient_behavior": "SYNTHETIC_PSEUDONYMOUS",
        },
        "customer_model": {
            "customers_per_branch": CUSTOMERS_PER_BRANCH,
            "households_per_branch": HOUSEHOLDS_PER_BRANCH,
            "patients_per_household": PATIENTS_PER_HOUSEHOLD,
            "direct_pii_generated": False,
            "identity_mode": "pseudonymous_synthetic_keys",
        },
        "workload_behavior": {
            "egypt_weekend": ["Friday", "Saturday"],
            "branch_demand_index_used": True,
            "branch_operating_hours_used": True,
            "service_modes_used_for_channel_mix": True,
            "branch_payment_mix_used": True,
            "branch_discount_ceiling_enforced": True,
            "long_tail_product_popularity": True,
            "quantity_distribution": "mostly_single_unit_with_small_multi_unit_tail",
            "demand_capture": "fulfilled_partial_and_out_of_stock_attempts",
            "lost_demand": "explicit_requested_fulfilled_lost_unit_reconciliation",
            "returns": "deterministic_low_rate_quarantine_returns",
            "inventory": "opening_stock_plus_per_sale_FEFO_like_single_batch_movements",
            "procurement": "opening_stock_purchase_orders_and_calibrated_receipt_delays",
            "customers": "known_anonymous_loyalty_delivery_and_household_profiles",
            "repeat_behavior": "stable_customer_affinity_and_chronic_repeat_pattern",
            "prescriptions": "privacy_safe_patient_and_prescription_context",
            "audit_strategy": "commit_before_fast_metric_finalize_no_full_table_rescan",
        },
        "safety": {
            "destructive_reset_default": False,
            "idempotent_run_key": True,
            "cloud_mutation": False,
            "local_postgres_mutation": True,
        },
    }


def write_history_contract(path: Path, contract: HistoryRunContract) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(history_contract(contract), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
