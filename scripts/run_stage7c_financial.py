"""Build Stage 7C production-like pricing and financial calibration artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pharmstock.finance import (
    CALIBRATED_PROVENANCE,
    FINANCIAL_MODEL_VERSION,
    RETAIL_PRICE_PROVENANCE,
    TAX_TREATMENT,
    build_branch_policies,
    build_product_economics,
    build_sample_financial_lines,
    export_financial_calibration,
)

DEFAULT_PRODUCTS = Path("artifacts/stage7a/egypt_product_master.csv")
DEFAULT_BRANCHES = Path("artifacts/stage7b/production_pharmacy_branches.csv")
DEFAULT_OUTPUT = Path("artifacts/stage7c")

EDA_PRICING_REFERENCE = (
    "https://edaegypt.gov.eg/ar/المركز-الإعلامي/الأخبار/"
    "رئيس-هيئة-الدواء-الدولة-المصرية-تدعم-توفير-كافة-الاحتياجات-الدوائية-"
    "للمريض-المصري-والدواء-المصري-يتمتع-بأعلى-معايير-الجودة/"
)
EDA_MARGIN_ENFORCEMENT_REFERENCE = (
    "https://www.edaegypt.gov.eg/en/media-center/news/"
    "the-egyptian-drug-authority-closes-a-number-of-warehouses-stores-in-violation-"
    "of-market-control/"
)
ETA_HEALTH_VAT_REFERENCE = (
    "https://eta.gov.eg/ar/news/"
    "altdylat-almqtrht-ly-qanwn-aldrybt-ly-alqymt-almdaft-tdm-alqta-alshy-walsnaat-altbyt"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build Stage 7C EGP retail-price and calibrated financial engine"
    )
    parser.add_argument("--products", type=Path, default=DEFAULT_PRODUCTS)
    parser.add_argument("--branches", type=Path, default=DEFAULT_BRANCHES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-lines", type=int, default=200)
    return parser.parse_args()


def _assumptions() -> dict[str, object]:
    return {
        "stage": "7C",
        "financial_model_version": FINANCIAL_MODEL_VERSION,
        "market": "EG",
        "currency": "EGP",
        "retail_price": {
            "provenance": RETAIL_PRICE_PROVENANCE,
            "description": "Observed public Egypt-market retail price carried from Stage 7A.",
            "official_eda_price_verified": False,
        },
        "purchase_cost_and_margin": {
            "provenance": CALIBRATED_PROVENANCE,
            "description": (
                "Deterministic digital-twin calibration. Not an EDA-approved pharmacist or "
                "distributor margin schedule."
            ),
            "modeled_margin_ranges_by_retail_band": {
                "0-50 EGP": "18%-25%",
                "50-200 EGP": "16%-23%",
                "200-1000 EGP": "14%-21.5%",
                "1000+ EGP": "12%-20%",
            },
        },
        "customer_discounts": {
            "provenance": CALIBRATED_PROVENANCE,
            "description": "Simulation ceiling only; not a regulatory discount entitlement.",
            "maximum_modeled_discount": "4%",
        },
        "tax": {
            "treatment": TAX_TREATMENT,
            "tax_rate": None,
            "tax_component_modeled": False,
            "reason": (
                "Stage 7C does not have a medicine-specific public source sufficient to infer "
                "one universal VAT rate, so no tax is decomposed from observed retail price."
            ),
        },
        "regulatory_references": [
            {
                "publisher": "Egyptian Drug Authority",
                "purpose": "Pricing review and regulated profit-margin context",
                "url": EDA_PRICING_REFERENCE,
            },
            {
                "publisher": "Egyptian Drug Authority",
                "purpose": "Enforcement of compulsory pricing and pharmacist margin decisions",
                "url": EDA_MARGIN_ENFORCEMENT_REFERENCE,
            },
            {
                "publisher": "Egyptian Tax Authority",
                "purpose": "Health-sector VAT context; not used to infer medicine tax rate",
                "url": ETA_HEALTH_VAT_REFERENCE,
            },
        ],
    }


def main() -> None:
    args = parse_args()
    if args.sample_lines <= 0:
        raise SystemExit("--sample-lines must be positive")

    stage7a_success = args.products.parent / "_SUCCESS"
    stage7b_success = args.branches.parent / "_SUCCESS"
    if not stage7a_success.is_file():
        raise SystemExit("Stage 7A _SUCCESS is required before Stage 7C")
    if not stage7b_success.is_file():
        raise SystemExit("Stage 7B _SUCCESS is required before Stage 7C")

    products = build_product_economics(args.products)
    branches = build_branch_policies(args.branches)
    samples = build_sample_financial_lines(
        products,
        branches,
        sample_size=args.sample_lines,
    )
    paths = export_financial_calibration(
        products=products,
        branches=branches,
        samples=samples,
        output_dir=args.output,
        assumptions=_assumptions(),
    )
    quality = json.loads(paths["quality"].read_text(encoding="utf-8"))

    print("=== PharmStock V2 / Stage 7C Production Pricing & Financial Engine ===")
    print(f"Products with retail price:       {len(products):,}")
    print(f"Branch commercial policies:       {len(branches):,}")
    print(f"Financial sample lines:           {len(samples):,}")
    print(f"Retail price provenance:          {RETAIL_PRICE_PROVENANCE}")
    print(f"Purchase cost provenance:         {CALIBRATED_PROVENANCE}")
    print("Official margin % claimed:        NO")
    print("Tax rate inferred/modelled:       NO")
    print(f"Tax treatment:                    {TAX_TREATMENT}")
    print("Currency:                         EGP")
    print(f"Retail median (EGP):              {quality['retail_price']['median']}")
    print(f"Purchase-cost median (EGP):       {quality['purchase_cost']['median']}")
    print(
        "Modeled gross-margin median:      "
        f"{DecimalText.percent(quality['modeled_gross_margin_pct']['median'])}"
    )
    print("Cloud mutation:                   NO")
    print("\nGenerated files:")
    for key in ("products", "branches", "samples", "assumptions", "quality"):
        print(f"  {paths[key]}")
    print("\nSTAGE_7C_STATUS=PASS")


class DecimalText:
    """Formatting helpers kept local to the CLI output."""

    @staticmethod
    def percent(value: str) -> str:
        return f"{float(value) * 100:.2f}%"


if __name__ == "__main__":
    main()
