from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pharmstock.simulation.pos_history import (
    DEFAULT_END_DATE,
    HISTORY_MODEL_VERSION,
    HISTORY_PROVENANCE,
    PROFILE_CONFIGS,
    HistoryProfile,
    history_contract,
    resolve_profile,
    run_token,
)
from scripts.run_checkpoint import checkpoint_command

ROOT = Path(__file__).resolve().parents[1]
SUPPORT_SQL = ROOT / "infra/docker/postgres/sql/005_stage7e_support.sql"
GENERATE_SQL = ROOT / "infra/docker/postgres/sql/006_generate_stage7e_history.sql"
VERIFY_SQL = ROOT / "infra/docker/postgres/sql/007_verify_stage7e_history.sql"
FINALIZE_SQL = ROOT / "infra/docker/postgres/sql/008_finalize_stage7e_metrics.sql"
RUNNER = ROOT / "scripts/run_stage7e_history.py"


def test_stage7e_profiles_have_small_acceptance_and_prod_like_paths() -> None:
    assert PROFILE_CONFIGS[HistoryProfile.DEV].branch_limit == 27
    assert PROFILE_CONFIGS[HistoryProfile.ACCEPTANCE].branch_limit == 5_000
    assert PROFILE_CONFIGS[HistoryProfile.ACCEPTANCE].days == 14
    assert PROFILE_CONFIGS[HistoryProfile.PROD_LIKE].branch_limit == 5_000
    assert PROFILE_CONFIGS[HistoryProfile.PROD_LIKE].days == 365
    assert PROFILE_CONFIGS[HistoryProfile.PROD_LIKE].min_sale_headers >= 30_000_000


def test_stage7e_acceptance_contract_targets_million_scale() -> None:
    contract = resolve_profile(HistoryProfile.ACCEPTANCE)
    assert contract.start_date == "2026-08-09"
    assert contract.end_date == "2026-08-22"
    assert contract.min_sale_headers >= 1_200_000
    assert contract.min_sale_lines >= 2_000_000
    assert contract.base_transactions_per_branch_day == 24


def test_stage7e_custom_contract_is_deterministic() -> None:
    first = resolve_profile(
        HistoryProfile.DEV,
        end_date=date(2026, 8, 22),
        days=5,
        branch_limit=27,
        base_transactions_per_branch_day=9,
    )
    second = resolve_profile(
        HistoryProfile.DEV,
        end_date=date(2026, 8, 22),
        days=5,
        branch_limit=27,
        base_transactions_per_branch_day=9,
    )
    assert first == second
    assert run_token(first) == run_token(second)
    assert len(run_token(first)) == 12


def test_stage7e_invalid_overrides_are_rejected() -> None:
    with pytest.raises(ValueError):
        resolve_profile(HistoryProfile.DEV, days=0)
    with pytest.raises(ValueError):
        resolve_profile(HistoryProfile.DEV, branch_limit=5_001)
    with pytest.raises(ValueError):
        resolve_profile(HistoryProfile.DEV, base_transactions_per_branch_day=0)


def test_stage7e_truth_boundary_is_explicit_and_customer_data_is_privacy_safe() -> None:
    contract = history_contract(resolve_profile(HistoryProfile.DEV))
    truth = contract["truth_boundary"]
    assert truth["product_identity"] == "PUBLIC_MARKET_EGYPT_FROM_STAGE7A"
    assert truth["retail_price"] == "PUBLIC_MARKET_EGYPT_FROM_STAGE7A"
    assert truth["pos_transactions"] == HISTORY_PROVENANCE
    assert truth["customer_behavior"] == "SYNTHETIC_CALIBRATED_PRIVACY_SAFE"
    assert truth["customer_direct_identifiers"] == "NOT_GENERATED"
    assert truth["patient_behavior"] == "SYNTHETIC_PSEUDONYMOUS"
    assert contract["run"]["history_model_version"] == HISTORY_MODEL_VERSION


def test_stage7e_support_sql_creates_audit_and_unlogged_work_tables() -> None:
    text = SUPPORT_SQL.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS audit.simulation_run" in text
    assert "CREATE OR REPLACE FUNCTION audit.hash_unit" in text
    assert "CREATE OR REPLACE FUNCTION audit.stage7e_receipt_delay_days" in text
    assert "CREATE TABLE IF NOT EXISTS pos.demand_attempt" in text
    assert "requested_units = fulfilled_units + lost_units" in text
    assert "CREATE UNLOGGED TABLE IF NOT EXISTS staging.stage7e_product_pool" in text
    assert "CREATE UNLOGGED TABLE IF NOT EXISTS staging.stage7e_sale_seed" in text
    assert "CREATE UNLOGGED TABLE IF NOT EXISTS staging.stage7e_sale_line_seed" in text


def test_stage7e_generator_uses_branch_demand_weekend_hours_and_service_modes() -> None:
    text = GENERATE_SQL.read_text(encoding="utf-8")
    assert "b.demand_index" in text
    assert "PARTITION BY b.governorate_code" in text
    assert "ranked.governorate_rank = 1" in text
    assert "extract(isodow FROM c.business_date)" in text
    assert "WHEN 5 THEN 0.88" in text
    assert "WHEN 6 THEN 0.96" in text
    assert "t.is_24_hours" in text
    assert "position('delivery' IN t.service_modes)" in text
    assert "ONLINE_FULFILLMENT" in text
    assert "CLICK_AND_COLLECT" in text


def test_stage7e_generator_enforces_finance_payment_and_long_tail_product_mix() -> None:
    text = GENERATE_SQL.read_text(encoding="utf-8")
    assert "power(l.product_u, 2.35)" in text
    assert "policy.customer_discount_ceiling_pct" in text
    assert "f.gross_sales_egp - f.discount_amount_egp" in text
    assert "sale.net_sales_egp" in text
    assert "CASH" in text
    assert "CARD" in text
    assert "DIGITAL_WALLET" in text
    assert "THIRD_PARTY_PAYER" in text


def test_stage7e_generator_builds_inventory_and_procurement_history() -> None:
    text = GENERATE_SQL.read_text(encoding="utf-8")
    for table in (
        "inventory.stock_batch",
        "inventory.inventory_position",
        "inventory.stock_movement",
        "procurement.supplier",
        "procurement.purchase_order",
        "procurement.purchase_order_line",
        "procurement.goods_receipt",
        "procurement.goods_receipt_line",
    ):
        assert f"INSERT INTO {table}" in text
    assert "movement_type" in text
    assert "'SALE'" in text
    assert "'GOODS_RECEIPT'" in text
    assert "audit.stage7e_receipt_delay_days" in text


def test_stage7e_generator_captures_partial_and_stockout_demand() -> None:
    text = GENERATE_SQL.read_text(encoding="utf-8")
    assert "INSERT INTO pos.demand_attempt" in text
    assert "'PARTIAL'" in text
    assert "'OUT_OF_STOCK'" in text
    assert "'NO_SELLABLE_STOCK'" in text
    assert "|partial-demand|" in text
    assert "|stockout-trigger|" in text


def test_stage7e_generator_has_low_rate_quarantine_returns() -> None:
    text = GENERATE_SQL.read_text(encoding="utf-8")
    assert "< 0.009" in text
    assert "INSERT INTO pos.return_header" in text
    assert "INSERT INTO pos.return_line" in text
    assert "'QUARANTINE'" in text


def test_stage7e_fast_finalizer_records_scale_finance_and_customer_metrics() -> None:
    text = FINALIZE_SQL.read_text(encoding="utf-8")
    for key in (
        "sale_header",
        "sale_line",
        "demand_attempt",
        "partial_demand_attempts",
        "stockout_demand_attempts",
        "lost_demand_units",
        "sale_movements",
        "purchase_orders",
        "goods_receipts",
        "delayed_goods_receipts",
        "return_rate",
        "customers",
        "households",
        "loyalty_accounts",
        "patients",
        "known_sales",
        "anonymous_sales",
        "prescription_sales",
        "chronic_repeat_sales",
    ):
        assert f"('{key}'," in text
    assert "FAST_STAGING_METRICS_NO_FULL_TABLE_RESCAN" in text



def test_stage7e_finalizer_avoids_large_operational_table_rescans() -> None:
    text = FINALIZE_SQL.read_text(encoding="utf-8")
    for forbidden in (
        "FROM pos.sale_header",
        "FROM pos.sale_line",
        "FROM pos.payment",
        "FROM inventory.stock_movement",
        "FROM inventory.stock_batch",
        "FROM procurement.purchase_order",
        "FROM procurement.goods_receipt",
    ):
        assert forbidden not in text
    assert "FROM staging.stage7e_sale_seed" in text
    assert "FROM staging.stage7e_sale_line_seed" in text


def test_stage7e_marks_audit_pass_only_after_python_acceptance() -> None:
    finalizer = FINALIZE_SQL.read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    assert "status = 'PASS'" not in finalizer
    assert "def _mark_run_pass" in runner
    assert "_mark_run_pass(contract)" in runner

def test_stage7e_verifier_uses_metrics_and_schema_guards_not_operational_rescans() -> None:
    text = VERIFY_SQL.read_text(encoding="utf-8")
    assert "audit.stage7e_run_metric" in text
    assert "demand_arithmetic_guard=" in text
    assert "header_financial_guard=" in text
    assert "line_financial_guard=" in text
    assert "payment_unique_guard=" in text
    assert "sale_customer_context_guard=" in text
    assert "customer_direct_identifier_columns=" in text
    assert "FROM pos.sale_line AS line" not in text
    assert "FROM inventory.stock_movement AS movement" not in text


def test_stage7e_generator_commits_before_audit_and_has_no_full_count_update() -> None:
    text = GENERATE_SQL.read_text(encoding="utf-8")
    assert "COMMIT;" in text
    assert "UPDATE audit.simulation_run" not in text
    assert "ANALYZE pos.sale_header" not in text
    assert "generated_counts = jsonb_build_object" not in text


def test_stage7e_customer_digital_twin_has_privacy_safe_entities() -> None:
    text = SUPPORT_SQL.read_text(encoding="utf-8")
    for table in (
        "customer.household",
        "customer.customer_profile",
        "customer.loyalty_account",
        "customer.patient_profile",
        "pos.prescription_context",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in text
    for field in (
        "customer_segment",
        "purchase_frequency_per_30d",
        "average_basket_size",
        "discount_sensitivity",
        "brand_loyalty_score",
        "generic_substitution_tendency",
        "preferred_payment_method",
        "delivery_preference",
        "prescription_purchase_ratio",
        "otc_purchase_ratio",
        "chronic_repeat_purchase_pattern",
        "last_purchase_at",
    ):
        assert field in text
    assert "direct_identifiers_generated boolean NOT NULL DEFAULT false" in text


def test_stage7e_sales_link_known_anonymous_loyalty_and_prescription_context() -> None:
    text = GENERATE_SQL.read_text(encoding="utf-8")
    assert "'ANONYMOUS'" in text
    assert "'KNOWN'" in text
    assert "'LOYALTY'" in text
    assert "'DELIVERY_REGISTERED'" in text
    assert "anonymous_customer_key" in text
    assert "loyalty_account_id" in text
    assert "INSERT INTO pos.prescription_context" in text
    assert "anonymous_patient_key" in text


def test_stage7e_chronic_customers_have_stable_product_affinity() -> None:
    text = GENERATE_SQL.read_text(encoding="utf-8")
    assert "s.chronic_repeat_purchase_pattern" in text
    assert "|chronic-product|" in text
    assert "s.customer_id::text" in text


def test_stage7e_materializes_stock_plan_to_avoid_repeat_heavy_grouping() -> None:
    text = GENERATE_SQL.read_text(encoding="utf-8")
    assert "INSERT INTO staging.stage7e_stock_plan" in text
    assert "FROM staging.stage7e_stock_plan AS stock" in text
    assert "TRUNCATE TABLE staging.stage7e_stock_plan" in text


def test_stage7e_runner_can_resume_committed_running_history() -> None:
    text = RUNNER.read_text(encoding="utf-8")
    assert "Resuming Stage 7E from committed RUNNING history" in text
    assert "FINALIZE_SQL" in text
    assert "skipping regeneration" in text


def test_stage7e_runner_requires_stage7d_and_guards_prod_like() -> None:
    text = RUNNER.read_text(encoding="utf-8")
    assert "artifacts/stage7d/_SUCCESS" in text
    assert "--allow-large-run" in text
    assert "tens of millions of rows" in text
    assert "demand_attempt_per_sale_line" in text
    assert "supplier_delay_mix_present" in text
    assert "STAGE_7E_STATUS=PASS" in text


def test_checkpoint_launcher_knows_stage7e() -> None:
    command = checkpoint_command("7e")
    assert command[-1] == "scripts/run_stage7e_history.py"


def test_default_history_end_date_is_last_closed_project_day() -> None:
    assert DEFAULT_END_DATE == date(2026, 8, 22)
