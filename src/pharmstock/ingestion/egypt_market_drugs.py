"""Egypt-oriented public-market pharmaceutical master ingestion.

Stage 7A intentionally separates three truth levels:

* Egyptian Drug Authority (EDA) EDDB / Pharma Data Hub are the regulatory authority.
* The default downloadable CSV is a public Egyptian-market snapshot released under CC0.
* Missing EDA registration numbers / GTINs are never fabricated; they remain pending verification.

The module is standard-library only so the local checkpoint can run without pandas.
"""

from __future__ import annotations

import csv
import hashlib
import shutil
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, UUID, uuid5

DEFAULT_EGYPT_MARKET_SOURCE_URL: Final[str] = (
    "https://raw.githubusercontent.com/karem505/egyptian-drug-database/"
    "main/data/egyptian-drugs.csv"
)
DEFAULT_SOURCE_REPOSITORY_URL: Final[str] = (
    "https://github.com/karem505/egyptian-drug-database"
)
DEFAULT_SOURCE_SNAPSHOT_LABEL: Final[str] = "2026-06"
DEFAULT_SOURCE_LICENSE: Final[str] = "CC0-1.0"
DEFAULT_MIN_ACCEPTED_PRODUCTS: Final[int] = 20_000
SOURCE_SYSTEM: Final[str] = "egyptian_drug_database_cc0"
PROVENANCE_CLASS: Final[str] = "PUBLIC_MARKET_EGYPT"
OFFICIAL_AUTHORITY: Final[str] = "Egyptian Drug Authority (EDA)"
OFFICIAL_REGISTRY: Final[str] = "Egyptian Drug Database (EDDB)"
OFFICIAL_VERIFICATION_STATE: Final[str] = "pending_eda_verification"

EXPECTED_SOURCE_COLUMNS: Final[tuple[str, ...]] = (
    "commercial_name_en",
    "commercial_name_ar",
    "scientific_name",
    "manufacturer",
    "drug_class",
    "route",
    "price_egp",
)

EXCLUDED_MARKET_MARKERS: Final[tuple[str, ...]] = (
    "(CANCELLED)",
    "(N/A YET)",
    "(ILLEGAL IMPORT)",
    "WITHDRAWN",
    "DISCONTINUED",
)

PRODUCT_MASTER_FIELDS: Final[tuple[str, ...]] = (
    "product_id",
    "market_product_key",
    "trade_name_en",
    "trade_name_ar",
    "scientific_name",
    "manufacturer",
    "drug_class",
    "route",
    "retail_price_egp",
    "currency",
    "market_code",
    "provenance_class",
    "synthetic_record",
    "source_system",
    "source_repository_url",
    "source_license",
    "source_snapshot_label",
    "source_record_number",
    "official_authority",
    "official_registry",
    "official_registration_verified",
    "registration_number",
    "gtin",
    "official_verification_state",
)

PRICE_HISTORY_FIELDS: Final[tuple[str, ...]] = (
    "price_observation_id",
    "product_id",
    "price_egp",
    "currency",
    "price_type",
    "observed_at",
    "source_snapshot_label",
    "source_system",
    "provenance_class",
    "official_price_verified",
)

EDA_VERIFICATION_FIELDS: Final[tuple[str, ...]] = (
    "product_id",
    "trade_name_en",
    "trade_name_ar",
    "scientific_name",
    "manufacturer",
    "market_price_egp",
    "verification_status",
    "eda_registration_number",
    "gtin",
    "eda_license_status",
    "eda_price_status",
    "eda_registration_expiry_date",
    "verified_at",
)


class EgyptMarketDrugError(RuntimeError):
    """Raised when a public Egyptian-market snapshot cannot be prepared safely."""


@dataclass(frozen=True, slots=True)
class EgyptMarketProduct:
    """One normalized Egyptian-market product observation.

    The record is a public-market observation, not an EDA registration assertion.
    """

    product_id: UUID
    market_product_key: str
    trade_name_en: str
    trade_name_ar: str
    scientific_name: str
    manufacturer: str
    drug_class: str
    route: str
    retail_price_egp: Decimal
    source_record_number: int

    def product_row(self, *, snapshot_label: str) -> dict[str, object]:
        return {
            "product_id": str(self.product_id),
            "market_product_key": self.market_product_key,
            "trade_name_en": self.trade_name_en,
            "trade_name_ar": self.trade_name_ar,
            "scientific_name": self.scientific_name,
            "manufacturer": self.manufacturer,
            "drug_class": self.drug_class,
            "route": self.route,
            "retail_price_egp": _decimal_text(self.retail_price_egp),
            "currency": "EGP",
            "market_code": "EG",
            "provenance_class": PROVENANCE_CLASS,
            "synthetic_record": "false",
            "source_system": SOURCE_SYSTEM,
            "source_repository_url": DEFAULT_SOURCE_REPOSITORY_URL,
            "source_license": DEFAULT_SOURCE_LICENSE,
            "source_snapshot_label": snapshot_label,
            "source_record_number": self.source_record_number,
            "official_authority": OFFICIAL_AUTHORITY,
            "official_registry": OFFICIAL_REGISTRY,
            "official_registration_verified": "false",
            "registration_number": "",
            "gtin": "",
            "official_verification_state": OFFICIAL_VERIFICATION_STATE,
        }

    def price_row(self, *, snapshot_label: str, observed_at: datetime) -> dict[str, object]:
        observation_key = (
            f"{SOURCE_SYSTEM}|{self.product_id}|{snapshot_label}|"
            f"{_decimal_text(self.retail_price_egp)}"
        )
        return {
            "price_observation_id": str(uuid5(NAMESPACE_URL, observation_key)),
            "product_id": str(self.product_id),
            "price_egp": _decimal_text(self.retail_price_egp),
            "currency": "EGP",
            "price_type": "retail_market_snapshot",
            "observed_at": observed_at.astimezone(UTC).isoformat(),
            "source_snapshot_label": snapshot_label,
            "source_system": SOURCE_SYSTEM,
            "provenance_class": PROVENANCE_CLASS,
            "official_price_verified": "false",
        }

    def verification_row(self) -> dict[str, object]:
        return {
            "product_id": str(self.product_id),
            "trade_name_en": self.trade_name_en,
            "trade_name_ar": self.trade_name_ar,
            "scientific_name": self.scientific_name,
            "manufacturer": self.manufacturer,
            "market_price_egp": _decimal_text(self.retail_price_egp),
            "verification_status": OFFICIAL_VERIFICATION_STATE,
            "eda_registration_number": "",
            "gtin": "",
            "eda_license_status": "",
            "eda_price_status": "",
            "eda_registration_expiry_date": "",
            "verified_at": "",
        }


@dataclass(frozen=True, slots=True)
class RejectedEgyptMarketRow:
    source_record_number: int
    reason: str
    trade_name_en: str
    raw_row: dict[str, str]


@dataclass(slots=True)
class EgyptMarketIngestionReport:
    source_rows: int = 0
    products: list[EgyptMarketProduct] = field(default_factory=list)
    rejected_rows: list[RejectedEgyptMarketRow] = field(default_factory=list)
    duplicate_rows_skipped: int = 0
    exclusion_reasons: Counter[str] = field(default_factory=Counter)

    @property
    def accepted_count(self) -> int:
        return len(self.products)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected_rows)


def download_or_copy_snapshot(
    destination: Path,
    *,
    source_url: str = DEFAULT_EGYPT_MARKET_SOURCE_URL,
    offline_file: Path | None = None,
    refresh: bool = False,
    timeout_seconds: float = 90.0,
) -> Path:
    """Materialize the source CSV without silently changing an existing cache."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not refresh and offline_file is None:
        return destination

    if offline_file is not None:
        if not offline_file.is_file():
            raise EgyptMarketDrugError(f"offline source file does not exist: {offline_file}")
        shutil.copy2(offline_file, destination)
        return destination

    request = Request(
        source_url,
        headers={
            "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.1",
            "User-Agent": "pharmstock-ai-platform/0.25.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            with destination.open("wb") as handle:
                shutil.copyfileobj(response, handle)
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise EgyptMarketDrugError(f"Egypt market snapshot download failed: {exc}") from exc

    if destination.stat().st_size < 10_000:
        destination.unlink(missing_ok=True)
        raise EgyptMarketDrugError("downloaded Egypt market snapshot is unexpectedly small")
    return destination


def ingest_egypt_market_csv(path: Path) -> EgyptMarketIngestionReport:
    """Normalize a CSV snapshot into high-confidence medicine records.

    Rows with no scientific composition are retained in the reject/audit output rather than being
    promoted into the medicine master. Obvious cancelled / unavailable / illegal-import markers are
    also excluded from the active market candidate master.
    """

    report = EgyptMarketIngestionReport()
    seen_keys: set[str] = set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        missing = [column for column in EXPECTED_SOURCE_COLUMNS if column not in fieldnames]
        if missing:
            raise EgyptMarketDrugError(f"source CSV missing columns: {', '.join(missing)}")

        for record_number, raw in enumerate(reader, start=1):
            report.source_rows += 1
            normalized_raw = {key: (value or "") for key, value in raw.items() if key is not None}
            try:
                product = normalize_egypt_market_row(
                    normalized_raw,
                    source_record_number=record_number,
                )
            except ValueError as exc:
                reason = str(exc)
                report.exclusion_reasons[reason] += 1
                report.rejected_rows.append(
                    RejectedEgyptMarketRow(
                        source_record_number=record_number,
                        reason=reason,
                        trade_name_en=_clean_text(normalized_raw.get("commercial_name_en")),
                        raw_row=normalized_raw,
                    )
                )
                continue

            if product.market_product_key in seen_keys:
                report.duplicate_rows_skipped += 1
                report.exclusion_reasons["duplicate_market_product"] += 1
                continue
            seen_keys.add(product.market_product_key)
            report.products.append(product)

    return report


def normalize_egypt_market_row(
    row: dict[str, str],
    *,
    source_record_number: int,
) -> EgyptMarketProduct:
    trade_name_en = _clean_text(row.get("commercial_name_en"))
    if not trade_name_en:
        raise ValueError("missing_trade_name")

    upper_name = trade_name_en.upper()
    for marker in EXCLUDED_MARKET_MARKERS:
        if marker in upper_name:
            raise ValueError(f"excluded_market_marker:{marker}")

    scientific_name = _clean_text(row.get("scientific_name"))
    if not scientific_name:
        raise ValueError("missing_scientific_name")

    price = _parse_positive_price(row.get("price_egp"))
    manufacturer = _clean_text(row.get("manufacturer")) or "UNKNOWN"
    drug_class = _clean_text(row.get("drug_class")) or "UNKNOWN"
    route = _normalize_route(row.get("route"))
    trade_name_ar = _clean_text(row.get("commercial_name_ar"))

    key_material = "|".join(
        (
            _key_text(trade_name_en),
            _key_text(scientific_name),
            _key_text(manufacturer),
            _key_text(route),
        )
    )
    market_product_key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
    product_id = uuid5(NAMESPACE_URL, f"pharmstock:eg-market:{market_product_key}")

    return EgyptMarketProduct(
        product_id=product_id,
        market_product_key=market_product_key,
        trade_name_en=trade_name_en,
        trade_name_ar=trade_name_ar,
        scientific_name=scientific_name,
        manufacturer=manufacturer,
        drug_class=drug_class,
        route=route,
        retail_price_egp=price,
        source_record_number=source_record_number,
    )


def quality_summary(report: EgyptMarketIngestionReport) -> dict[str, object]:
    prices = sorted(product.retail_price_egp for product in report.products)
    manufacturers = {product.manufacturer for product in report.products}
    classes = {product.drug_class for product in report.products}
    routes = Counter(product.route for product in report.products)
    arabic_count = sum(bool(product.trade_name_ar) for product in report.products)

    return {
        "source_rows": report.source_rows,
        "accepted_products": report.accepted_count,
        "rejected_rows": report.rejected_count,
        "duplicate_rows_skipped": report.duplicate_rows_skipped,
        "acceptance_rate_pct": _percent(report.accepted_count, report.source_rows),
        "arabic_name_coverage_pct": _percent(arabic_count, report.accepted_count),
        "price_coverage_pct": 100.0 if report.products else 0.0,
        "scientific_name_coverage_pct": 100.0 if report.products else 0.0,
        "unique_manufacturers": len(manufacturers),
        "unique_drug_classes": len(classes),
        "unique_routes": len(routes),
        "top_routes": routes.most_common(12),
        "price_egp": {
            "min": _decimal_text(prices[0]) if prices else None,
            "median": _decimal_text(_quantile(prices, 0.50)) if prices else None,
            "p95": _decimal_text(_quantile(prices, 0.95)) if prices else None,
            "max": _decimal_text(prices[-1]) if prices else None,
        },
        "exclusion_reasons": dict(sorted(report.exclusion_reasons.items())),
        "provenance_class": PROVENANCE_CLASS,
        "synthetic_product_rows": 0,
        "official_registration_verified_rows": 0,
        "official_price_verified_rows": 0,
        "eda_verification_required_rows": report.accepted_count,
    }


def validate_report(
    report: EgyptMarketIngestionReport,
    *,
    min_accepted_products: int = DEFAULT_MIN_ACCEPTED_PRODUCTS,
) -> tuple[str, ...]:
    issues: list[str] = []
    if report.accepted_count < min_accepted_products:
        issues.append(
            f"accepted products {report.accepted_count:,} below required {min_accepted_products:,}"
        )
    product_ids = [product.product_id for product in report.products]
    if len(product_ids) != len(set(product_ids)):
        issues.append("duplicate product_id detected")
    keys = [product.market_product_key for product in report.products]
    if len(keys) != len(set(keys)):
        issues.append("duplicate market_product_key detected")
    if any(product.retail_price_egp <= 0 for product in report.products):
        issues.append("non-positive retail price detected")
    return tuple(issues)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _clean_text(value: str | None) -> str:
    return " ".join((value or "").replace("\ufeff", "").split())


def _key_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _normalize_route(value: str | None) -> str:
    cleaned = _clean_text(value).upper()
    if not cleaned or cleaned in {".", "N/A", "NA"}:
        return "UNKNOWN"
    return cleaned


def _parse_positive_price(value: str | None) -> Decimal:
    cleaned = _clean_text(value).replace(",", "")
    if not cleaned:
        raise ValueError("missing_price")
    try:
        price = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError("invalid_price") from exc
    if not price.is_finite() or price <= 0:
        raise ValueError("non_positive_price")
    if price > Decimal("1000000"):
        raise ValueError("implausible_price")
    return price.quantize(Decimal("0.01"))


def _decimal_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _percent(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator * 100.0 / denominator, 2)


def _quantile(values: list[Decimal], q: float) -> Decimal:
    if not values:
        raise ValueError("quantile requires values")
    index = round((len(values) - 1) * q)
    return values[index]
