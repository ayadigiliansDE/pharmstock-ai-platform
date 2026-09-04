from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

import pytest

from pharmstock.finance import (
    CALIBRATED_PROVENANCE,
    FINANCIAL_MODEL_VERSION,
    RETAIL_PRICE_PROVENANCE,
    TAX_TREATMENT,
    FinancialCalibrationError,
    build_branch_policies,
    build_product_economics,
    build_sample_financial_lines,
    calculate_sale_line_financials,
    export_financial_calibration,
    financial_quality_report,
)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _product_rows() -> list[dict[str, object]]:
    return [
        {
            "product_id": "p1",
            "trade_name_en": "Medicine A",
            "scientific_name": "Ingredient A",
            "retail_price_egp": "25.00",
        },
        {
            "product_id": "p2",
            "trade_name_en": "Medicine B",
            "scientific_name": "Ingredient B",
            "retail_price_egp": "250.00",
        },
    ]


def _branch_rows() -> list[dict[str, object]]:
    return [
        {
            "branch_id": "b1",
            "governorate_code": "EG-C",
            "governorate": "Cairo",
            "locality_type": "urban",
            "organization_type": "chain",
            "pharmacy_type": "community",
            "scale": "large",
        },
        {
            "branch_id": "b2",
            "governorate_code": "EG-MN",
            "governorate": "Minya",
            "locality_type": "rural",
            "organization_type": "independent",
            "pharmacy_type": "community",
            "scale": "small",
        },
    ]


def test_sale_line_financials_reconcile() -> None:
    result = calculate_sale_line_financials(
        quantity=3,
        retail_unit_price_egp=Decimal("100"),
        purchase_cost_egp=Decimal("80"),
        discount_pct=Decimal("0.05"),
    )
    assert result.gross_sales_egp == Decimal("300.00")
    assert result.discount_amount_egp == Decimal("15.00")
    assert result.net_sales_egp == Decimal("285.00")
    assert result.cogs_egp == Decimal("240.00")
    assert result.gross_profit_egp == Decimal("45.00")


def test_sale_line_rejects_cost_above_retail() -> None:
    with pytest.raises(FinancialCalibrationError):
        calculate_sale_line_financials(
            quantity=1,
            retail_unit_price_egp=Decimal("100"),
            purchase_cost_egp=Decimal("101"),
        )


def test_product_economics_keep_real_price_and_calibrate_cost(tmp_path: Path) -> None:
    path = tmp_path / "products.csv"
    _write_csv(path, _product_rows())
    products = build_product_economics(path)
    assert len(products) == 2
    assert products[0].retail_price_egp == Decimal("25.00")
    assert products[0].purchase_cost_egp < products[0].retail_price_egp
    assert Decimal("0.12") <= products[0].modeled_gross_margin_pct <= Decimal("0.25")


def test_product_economics_are_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "products.csv"
    _write_csv(path, _product_rows())
    assert build_product_economics(path) == build_product_economics(path)


def test_duplicate_product_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "products.csv"
    rows = _product_rows()
    rows[1]["product_id"] = "p1"
    _write_csv(path, rows)
    with pytest.raises(FinancialCalibrationError, match="unique"):
        build_product_economics(path)


def test_branch_policy_payment_mix_reconciles(tmp_path: Path) -> None:
    path = tmp_path / "branches.csv"
    _write_csv(path, _branch_rows())
    policies = build_branch_policies(path)
    for item in policies:
        total = (
            item.cash_share
            + item.card_share
            + item.digital_wallet_share
            + item.third_party_payer_share
        )
        assert total == Decimal("1.0000")
        assert item.customer_discount_ceiling_pct <= Decimal("0.0400")


def test_branch_policies_are_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "branches.csv"
    _write_csv(path, _branch_rows())
    assert build_branch_policies(path) == build_branch_policies(path)


def test_sample_lines_reference_known_entities_and_reconcile(tmp_path: Path) -> None:
    products_path = tmp_path / "products.csv"
    branches_path = tmp_path / "branches.csv"
    _write_csv(products_path, _product_rows())
    _write_csv(branches_path, _branch_rows())
    products = build_product_economics(products_path)
    branches = build_branch_policies(branches_path)
    samples = build_sample_financial_lines(products, branches, sample_size=20)
    report = financial_quality_report(products, branches, samples)
    assert report["status"] == "PASS"
    assert report["checks"]["sample_financials_reconcile"] is True


def test_export_preserves_provenance_and_tax_boundary(tmp_path: Path) -> None:
    products_path = tmp_path / "products.csv"
    branches_path = tmp_path / "branches.csv"
    _write_csv(products_path, _product_rows())
    _write_csv(branches_path, _branch_rows())
    products = build_product_economics(products_path)
    branches = build_branch_policies(branches_path)
    samples = build_sample_financial_lines(products, branches, sample_size=5)
    paths = export_financial_calibration(
        products=products,
        branches=branches,
        samples=samples,
        output_dir=tmp_path / "out",
        assumptions={"tax": {"treatment": TAX_TREATMENT, "tax_rate": None}},
    )
    with paths["products"].open(encoding="utf-8-sig") as handle:
        row = next(csv.DictReader(handle))
    assert row["retail_price_provenance"] == RETAIL_PRICE_PROVENANCE
    assert row["cost_provenance"] == CALIBRATED_PROVENANCE
    assert row["tax_treatment"] == TAX_TREATMENT
    assert row["tax_component_modeled"] == "false"
    assert row["financial_model_version"] == FINANCIAL_MODEL_VERSION


def test_quality_report_never_claims_official_margin_or_tax(tmp_path: Path) -> None:
    products_path = tmp_path / "products.csv"
    branches_path = tmp_path / "branches.csv"
    _write_csv(products_path, _product_rows())
    _write_csv(branches_path, _branch_rows())
    products = build_product_economics(products_path)
    branches = build_branch_policies(branches_path)
    samples = build_sample_financial_lines(products, branches, sample_size=5)
    report = financial_quality_report(products, branches, samples)
    assert report["official_margin_percentage_claimed"] is False
    assert report["official_tax_rate_claimed"] is False


def test_checkpoint_launcher_knows_stage7c() -> None:
    from scripts.run_checkpoint import checkpoint_command

    command = checkpoint_command("7c")
    assert command[-1] == "scripts/run_stage7c_financial.py"


def test_assumptions_can_represent_null_tax_rate() -> None:
    payload = json.dumps({"tax_rate": None})
    assert '"tax_rate": null' in payload
