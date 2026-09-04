"""Production-like pharmacy pricing and financial calibration for Egypt.

Stage 7C separates observed market retail prices from calibrated internal economics.
Observed retail prices come from Stage 7A and retain PUBLIC_MARKET_EGYPT provenance.
Purchase costs, gross margins, branch discount ceilings, payment mix, and reserves are
SYNTHETIC_CALIBRATED values used by the digital twin. They are not EDA-approved margins.

Tax is deliberately not decomposed from the observed retail price because Stage 7C does
not have a sufficiently specific public source that supports a universal medicine VAT
rate. Downstream consumers must not infer one from this model.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Final

MONEY_QUANTUM: Final[Decimal] = Decimal("0.01")
RATE_QUANTUM: Final[Decimal] = Decimal("0.0001")
FINANCIAL_MODEL_VERSION: Final[str] = "EG_FINANCIAL_CALIBRATION_V1"
RETAIL_PRICE_PROVENANCE: Final[str] = "PUBLIC_MARKET_EGYPT"
CALIBRATED_PROVENANCE: Final[str] = "SYNTHETIC_CALIBRATED"
TAX_TREATMENT: Final[str] = "NOT_INFERRED_NO_TAX_DECOMPOSITION"

# These ranges are explicit simulation assumptions, not regulatory margin assertions.
MARGIN_RANGES: Final[tuple[tuple[Decimal, Decimal, Decimal], ...]] = (
    (Decimal("50"), Decimal("0.1800"), Decimal("0.2500")),
    (Decimal("200"), Decimal("0.1600"), Decimal("0.2300")),
    (Decimal("1000"), Decimal("0.1400"), Decimal("0.2150")),
    (Decimal("999999999"), Decimal("0.1200"), Decimal("0.2000")),
)

PRODUCT_ECONOMICS_FIELDS: Final[tuple[str, ...]] = (
    "product_id",
    "trade_name_en",
    "scientific_name",
    "retail_price_egp",
    "retail_price_provenance",
    "official_retail_price_verified",
    "purchase_cost_egp",
    "cost_provenance",
    "gross_profit_per_unit_egp",
    "modeled_gross_margin_pct",
    "price_band",
    "currency",
    "tax_treatment",
    "tax_component_modeled",
    "financial_model_version",
)

BRANCH_POLICY_FIELDS: Final[tuple[str, ...]] = (
    "branch_id",
    "governorate_code",
    "governorate",
    "locality_type",
    "organization_type",
    "pharmacy_type",
    "scale",
    "customer_discount_ceiling_pct",
    "shrinkage_reserve_pct",
    "cash_share",
    "card_share",
    "digital_wallet_share",
    "third_party_payer_share",
    "commercial_policy_provenance",
    "financial_model_version",
)

SAMPLE_LINE_FIELDS: Final[tuple[str, ...]] = (
    "sample_line_id",
    "product_id",
    "branch_id",
    "quantity",
    "retail_unit_price_egp",
    "discount_pct",
    "selling_unit_price_egp",
    "gross_sales_egp",
    "discount_amount_egp",
    "net_sales_egp",
    "cogs_egp",
    "gross_profit_egp",
    "gross_margin_pct",
    "tax_treatment",
)


class FinancialCalibrationError(RuntimeError):
    """Raised when Stage 7C inputs or financial reconciliation are invalid."""


@dataclass(frozen=True, slots=True)
class ProductEconomics:
    product_id: str
    trade_name_en: str
    scientific_name: str
    retail_price_egp: Decimal
    purchase_cost_egp: Decimal
    gross_profit_per_unit_egp: Decimal
    modeled_gross_margin_pct: Decimal
    price_band: str

    def row(self) -> dict[str, object]:
        return {
            "product_id": self.product_id,
            "trade_name_en": self.trade_name_en,
            "scientific_name": self.scientific_name,
            "retail_price_egp": _money_text(self.retail_price_egp),
            "retail_price_provenance": RETAIL_PRICE_PROVENANCE,
            "official_retail_price_verified": "false",
            "purchase_cost_egp": _money_text(self.purchase_cost_egp),
            "cost_provenance": CALIBRATED_PROVENANCE,
            "gross_profit_per_unit_egp": _money_text(self.gross_profit_per_unit_egp),
            "modeled_gross_margin_pct": _rate_text(self.modeled_gross_margin_pct),
            "price_band": self.price_band,
            "currency": "EGP",
            "tax_treatment": TAX_TREATMENT,
            "tax_component_modeled": "false",
            "financial_model_version": FINANCIAL_MODEL_VERSION,
        }


@dataclass(frozen=True, slots=True)
class BranchCommercialPolicy:
    branch_id: str
    governorate_code: str
    governorate: str
    locality_type: str
    organization_type: str
    pharmacy_type: str
    scale: str
    customer_discount_ceiling_pct: Decimal
    shrinkage_reserve_pct: Decimal
    cash_share: Decimal
    card_share: Decimal
    digital_wallet_share: Decimal
    third_party_payer_share: Decimal

    def row(self) -> dict[str, object]:
        value = asdict(self)
        for key in (
            "customer_discount_ceiling_pct",
            "shrinkage_reserve_pct",
            "cash_share",
            "card_share",
            "digital_wallet_share",
            "third_party_payer_share",
        ):
            value[key] = _rate_text(value[key])
        value["commercial_policy_provenance"] = CALIBRATED_PROVENANCE
        value["financial_model_version"] = FINANCIAL_MODEL_VERSION
        return value


@dataclass(frozen=True, slots=True)
class SaleLineFinancials:
    quantity: int
    retail_unit_price_egp: Decimal
    discount_pct: Decimal
    selling_unit_price_egp: Decimal
    gross_sales_egp: Decimal
    discount_amount_egp: Decimal
    net_sales_egp: Decimal
    cogs_egp: Decimal
    gross_profit_egp: Decimal
    gross_margin_pct: Decimal


def calculate_sale_line_financials(
    *,
    quantity: int,
    retail_unit_price_egp: Decimal,
    purchase_cost_egp: Decimal,
    discount_pct: Decimal = Decimal("0"),
) -> SaleLineFinancials:
    """Calculate financially reconciled values for one future POS sale line."""

    if quantity <= 0:
        raise FinancialCalibrationError("quantity must be positive")
    if retail_unit_price_egp <= 0 or purchase_cost_egp <= 0:
        raise FinancialCalibrationError("prices and costs must be positive")
    if purchase_cost_egp > retail_unit_price_egp:
        raise FinancialCalibrationError("purchase cost cannot exceed retail price")
    if discount_pct < 0 or discount_pct >= 1:
        raise FinancialCalibrationError("discount_pct must be in [0, 1)")

    gross_sales = _money(retail_unit_price_egp * quantity)
    discount_amount = _money(gross_sales * discount_pct)
    net_sales = _money(gross_sales - discount_amount)
    selling_unit = _money(net_sales / quantity)
    cogs = _money(purchase_cost_egp * quantity)
    gross_profit = _money(net_sales - cogs)
    margin = Decimal("0") if net_sales == 0 else _rate(gross_profit / net_sales)
    return SaleLineFinancials(
        quantity=quantity,
        retail_unit_price_egp=_money(retail_unit_price_egp),
        discount_pct=_rate(discount_pct),
        selling_unit_price_egp=selling_unit,
        gross_sales_egp=gross_sales,
        discount_amount_egp=discount_amount,
        net_sales_egp=net_sales,
        cogs_egp=cogs,
        gross_profit_egp=gross_profit,
        gross_margin_pct=margin,
    )


def build_product_economics(product_master_csv: Path) -> list[ProductEconomics]:
    rows = _read_csv(product_master_csv)
    if not rows:
        raise FinancialCalibrationError("Stage 7A product master is empty")

    result: list[ProductEconomics] = []
    seen: set[str] = set()
    for row in rows:
        product_id = row.get("product_id", "").strip()
        if not product_id or product_id in seen:
            raise FinancialCalibrationError("product_id must be present and unique")
        seen.add(product_id)
        retail = _parse_positive_money(row.get("retail_price_egp", ""), "retail_price_egp")
        lower, upper, band = _margin_bounds(retail)
        unit = _deterministic_unit_interval(f"product-margin|{product_id}")
        margin = _rate(lower + (upper - lower) * unit)
        cost = _money(retail * (Decimal("1") - margin))
        gross_profit = _money(retail - cost)
        result.append(
            ProductEconomics(
                product_id=product_id,
                trade_name_en=row.get("trade_name_en", "").strip(),
                scientific_name=row.get("scientific_name", "").strip(),
                retail_price_egp=retail,
                purchase_cost_egp=cost,
                gross_profit_per_unit_egp=gross_profit,
                modeled_gross_margin_pct=margin,
                price_band=band,
            )
        )
    return result


def build_branch_policies(branch_csv: Path) -> list[BranchCommercialPolicy]:
    rows = _read_csv(branch_csv)
    if not rows:
        raise FinancialCalibrationError("Stage 7B branch master is empty")

    policies: list[BranchCommercialPolicy] = []
    seen: set[str] = set()
    for row in rows:
        branch_id = row.get("branch_id", "").strip()
        if not branch_id or branch_id in seen:
            raise FinancialCalibrationError("branch_id must be present and unique")
        seen.add(branch_id)
        scale = row.get("scale", "small").strip()
        locality = row.get("locality_type", "urban").strip()
        org_type = row.get("organization_type", "independent").strip()
        pharmacy_type = row.get("pharmacy_type", "community").strip()

        discount_base = {
            "small": Decimal("0.0100"),
            "medium": Decimal("0.0150"),
            "large": Decimal("0.0200"),
            "flagship": Decimal("0.0250"),
        }.get(scale, Decimal("0.0100"))
        if org_type in {"chain", "digital_operator"}:
            discount_base += Decimal("0.0050")
        discount_noise = _deterministic_rate(
            f"discount|{branch_id}",
            Decimal("0"),
            Decimal("0.0050"),
        )
        discount_ceiling = min(Decimal("0.0400"), discount_base + discount_noise)

        shrinkage = _deterministic_rate(
            f"shrinkage|{branch_id}",
            Decimal("0.0020"),
            Decimal("0.0120"),
        )
        payment = _payment_mix(branch_id, locality, pharmacy_type)
        policies.append(
            BranchCommercialPolicy(
                branch_id=branch_id,
                governorate_code=row.get("governorate_code", "").strip(),
                governorate=row.get("governorate", "").strip(),
                locality_type=locality,
                organization_type=org_type,
                pharmacy_type=pharmacy_type,
                scale=scale,
                customer_discount_ceiling_pct=_rate(discount_ceiling),
                shrinkage_reserve_pct=shrinkage,
                cash_share=payment[0],
                card_share=payment[1],
                digital_wallet_share=payment[2],
                third_party_payer_share=payment[3],
            )
        )
    return policies


def build_sample_financial_lines(
    products: list[ProductEconomics],
    branches: list[BranchCommercialPolicy],
    *,
    sample_size: int = 200,
) -> list[dict[str, object]]:
    if sample_size <= 0:
        raise ValueError("sample_size must be positive")
    if not products or not branches:
        raise FinancialCalibrationError("products and branches are required")

    rows: list[dict[str, object]] = []
    for index in range(sample_size):
        product = products[(index * 97) % len(products)]
        branch = branches[(index * 53) % len(branches)]
        quantity = 1 + int(
            _deterministic_unit_interval(f"quantity|{product.product_id}|{branch.branch_id}")
            * Decimal("4")
        )
        discount_fraction = _deterministic_unit_interval(
            f"line-discount|{product.product_id}|{branch.branch_id}"
        )
        discount_pct = _rate(branch.customer_discount_ceiling_pct * discount_fraction)
        financial = calculate_sale_line_financials(
            quantity=quantity,
            retail_unit_price_egp=product.retail_price_egp,
            purchase_cost_egp=product.purchase_cost_egp,
            discount_pct=discount_pct,
        )
        rows.append(
            {
                "sample_line_id": f"S7C-{index + 1:06d}",
                "product_id": product.product_id,
                "branch_id": branch.branch_id,
                "quantity": financial.quantity,
                "retail_unit_price_egp": _money_text(financial.retail_unit_price_egp),
                "discount_pct": _rate_text(financial.discount_pct),
                "selling_unit_price_egp": _money_text(financial.selling_unit_price_egp),
                "gross_sales_egp": _money_text(financial.gross_sales_egp),
                "discount_amount_egp": _money_text(financial.discount_amount_egp),
                "net_sales_egp": _money_text(financial.net_sales_egp),
                "cogs_egp": _money_text(financial.cogs_egp),
                "gross_profit_egp": _money_text(financial.gross_profit_egp),
                "gross_margin_pct": _rate_text(financial.gross_margin_pct),
                "tax_treatment": TAX_TREATMENT,
            }
        )
    return rows


def financial_quality_report(
    products: list[ProductEconomics],
    branches: list[BranchCommercialPolicy],
    samples: list[dict[str, object]],
) -> dict[str, object]:
    product_ids = {item.product_id for item in products}
    branch_ids = {item.branch_id for item in branches}
    product_checks = {
        "product_ids_unique": len(product_ids) == len(products),
        "positive_retail_prices": all(item.retail_price_egp > 0 for item in products),
        "positive_purchase_costs": all(item.purchase_cost_egp > 0 for item in products),
        "cost_not_above_retail": all(
            item.purchase_cost_egp <= item.retail_price_egp for item in products
        ),
        "margin_within_model_bounds": all(
            Decimal("0.12") <= item.modeled_gross_margin_pct <= Decimal("0.25")
            for item in products
        ),
    }
    branch_checks = {
        "branch_ids_unique": len(branch_ids) == len(branches),
        "discount_ceiling_bounded": all(
            Decimal("0") <= item.customer_discount_ceiling_pct <= Decimal("0.04")
            for item in branches
        ),
        "payment_mix_reconciles": all(
            abs(
                item.cash_share
                + item.card_share
                + item.digital_wallet_share
                + item.third_party_payer_share
                - Decimal("1")
            )
            <= Decimal("0.0001")
            for item in branches
        ),
    }
    sample_checks = {
        "sample_rows_present": len(samples) > 0,
        "all_samples_reference_products": all(row["product_id"] in product_ids for row in samples),
        "all_samples_reference_branches": all(row["branch_id"] in branch_ids for row in samples),
        "sample_financials_reconcile": all(_sample_row_reconciles(row) for row in samples),
    }
    checks = {**product_checks, **branch_checks, **sample_checks}
    if not all(checks.values()):
        raise FinancialCalibrationError(f"Stage 7C quality checks failed: {checks}")

    retail_values = [item.retail_price_egp for item in products]
    purchase_values = [item.purchase_cost_egp for item in products]
    margin_values = [item.modeled_gross_margin_pct for item in products]
    return {
        "status": "PASS",
        "checks": checks,
        "product_count": len(products),
        "branch_policy_count": len(branches),
        "sample_transaction_lines": len(samples),
        "retail_price": _decimal_summary(retail_values),
        "purchase_cost": _decimal_summary(purchase_values),
        "modeled_gross_margin_pct": _decimal_summary(margin_values),
        "retail_price_provenance": RETAIL_PRICE_PROVENANCE,
        "purchase_cost_provenance": CALIBRATED_PROVENANCE,
        "tax_treatment": TAX_TREATMENT,
        "official_margin_percentage_claimed": False,
        "official_tax_rate_claimed": False,
    }


def export_financial_calibration(
    *,
    products: list[ProductEconomics],
    branches: list[BranchCommercialPolicy],
    samples: list[dict[str, object]],
    output_dir: Path,
    assumptions: dict[str, object],
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "products": output_dir / "product_unit_economics.csv",
        "branches": output_dir / "branch_commercial_policy.csv",
        "samples": output_dir / "sample_transaction_financials.csv",
        "assumptions": output_dir / "financial_model_assumptions.json",
        "quality": output_dir / "financial_quality_report.json",
        "success": output_dir / "_SUCCESS",
    }
    _write_csv(paths["products"], PRODUCT_ECONOMICS_FIELDS, [item.row() for item in products])
    _write_csv(paths["branches"], BRANCH_POLICY_FIELDS, [item.row() for item in branches])
    _write_csv(paths["samples"], SAMPLE_LINE_FIELDS, samples)
    paths["assumptions"].write_text(
        json.dumps(assumptions, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    quality = financial_quality_report(products, branches, samples)
    paths["quality"].write_text(
        json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    paths["success"].write_text("STAGE_7C_STATUS=PASS\n", encoding="utf-8")
    return paths


def _payment_mix(
    branch_id: str,
    locality_type: str,
    pharmacy_type: str,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    if locality_type == "rural":
        base = [Decimal("0.70"), Decimal("0.18"), Decimal("0.07"), Decimal("0.05")]
    else:
        base = [Decimal("0.42"), Decimal("0.34"), Decimal("0.13"), Decimal("0.11")]
    if pharmacy_type == "hospital":
        base = [Decimal("0.25"), Decimal("0.30"), Decimal("0.08"), Decimal("0.37")]
    elif pharmacy_type == "fulfillment_center":
        base = [Decimal("0.12"), Decimal("0.42"), Decimal("0.36"), Decimal("0.10")]

    jitter = _deterministic_rate(f"payment|{branch_id}", Decimal("-0.025"), Decimal("0.025"))
    base[0] = max(Decimal("0.05"), base[0] + jitter)
    base[1] = max(Decimal("0.05"), base[1] - jitter)
    total = sum(base)
    normalized = [_rate(value / total) for value in base]
    normalized[-1] = _rate(Decimal("1") - sum(normalized[:-1]))
    return normalized[0], normalized[1], normalized[2], normalized[3]


def _margin_bounds(retail: Decimal) -> tuple[Decimal, Decimal, str]:
    bands = (
        (Decimal("50"), "0-50 EGP"),
        (Decimal("200"), "50-200 EGP"),
        (Decimal("1000"), "200-1000 EGP"),
        (Decimal("999999999"), "1000+ EGP"),
    )
    for (threshold, lower, upper), (_, label) in zip(MARGIN_RANGES, bands, strict=True):
        if retail <= threshold:
            return lower, upper, label
    raise AssertionError("unreachable price band")


def _sample_row_reconciles(row: dict[str, object]) -> bool:
    gross = Decimal(str(row["gross_sales_egp"]))
    discount = Decimal(str(row["discount_amount_egp"]))
    net = Decimal(str(row["net_sales_egp"]))
    cogs = Decimal(str(row["cogs_egp"]))
    profit = Decimal(str(row["gross_profit_egp"]))
    return _money(gross - discount) == net and _money(net - cogs) == profit


def _decimal_summary(values: list[Decimal]) -> dict[str, str]:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        median = ordered[midpoint]
    else:
        median = (ordered[midpoint - 1] + ordered[midpoint]) / 2
    average = sum(values) / len(values)
    return {
        "min": _money_text(min(values)) if max(values) > Decimal("1") else _rate_text(min(values)),
        "median": _money_text(median) if max(values) > Decimal("1") else _rate_text(median),
        "mean": _money_text(average) if max(values) > Decimal("1") else _rate_text(average),
        "max": _money_text(max(values)) if max(values) > Decimal("1") else _rate_text(max(values)),
    }


def _deterministic_unit_interval(key: str) -> Decimal:
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    integer = int.from_bytes(digest[:8], "big")
    denominator = Decimal(2**64 - 1)
    return Decimal(integer) / denominator


def _deterministic_rate(key: str, lower: Decimal, upper: Decimal) -> Decimal:
    return _rate(lower + (upper - lower) * _deterministic_unit_interval(key))


def _parse_positive_money(value: str, field: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except Exception as exc:  # Decimal raises several value/type errors
        raise FinancialCalibrationError(f"invalid {field}: {value!r}") from exc
    if parsed <= 0:
        raise FinancialCalibrationError(f"{field} must be positive")
    return _money(parsed)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FinancialCalibrationError(f"required input does not exist: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(
    path: Path,
    fieldnames: Iterable[str],
    rows: Iterable[dict[str, object]],
) -> None:
    rows = list(rows)
    if not rows:
        raise FinancialCalibrationError(f"cannot write empty file: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _rate(value: Decimal) -> Decimal:
    return value.quantize(RATE_QUANTUM, rounding=ROUND_HALF_UP)


def _money_text(value: Decimal) -> str:
    return f"{_money(value):.2f}"


def _rate_text(value: Decimal) -> str:
    return f"{_rate(value):.4f}"
