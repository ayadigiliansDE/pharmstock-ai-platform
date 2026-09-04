"""openFDA NDC ingestion for the PharmStock canonical product master.

This module keeps three concerns separate:
1. transport: download official source records;
2. normalization: map source-specific JSON to canonical Product objects;
3. persistence/export: handled by the stage runner, not the client.

The NDC source is authoritative for the U.S. market only. It must never be
presented as Egyptian registration data.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from pharmstock.domain.product import (
    ActiveIngredient,
    PrescriptionStatus,
    Product,
    ProductIdentifiers,
    ProductSource,
    RegulatoryStatus,
)

OPENFDA_NDC_ENDPOINT = "https://api.fda.gov/drug/ndc.json"
DEFAULT_PAGE_SIZE = 100
MAX_SAFE_SKIP = 25_000


class OpenFdaError(RuntimeError):
    """Raised when openFDA cannot be queried reliably."""


@dataclass(frozen=True, slots=True)
class OpenFdaPage:
    """One page returned by the NDC endpoint."""

    records: tuple[dict[str, Any], ...]
    last_updated: str | None
    total_matches: int | None
    skip: int
    limit: int


class OpenFdaNdcClient:
    """Small resilient client for the official openFDA NDC endpoint.

    We intentionally use Python's standard library here so Stage 2B does not
    add an HTTP framework dependency merely to download JSON.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        user_agent: str = "pharmstock-ai-platform/0.6.0",
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        self._api_key = api_key.strip() if api_key and api_key.strip() else None
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._user_agent = user_agent

    def fetch_page(self, *, limit: int = DEFAULT_PAGE_SIZE, skip: int = 0) -> OpenFdaPage:
        if not 1 <= limit <= DEFAULT_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {DEFAULT_PAGE_SIZE}")
        if not 0 <= skip <= MAX_SAFE_SKIP:
            raise ValueError(f"skip must be between 0 and {MAX_SAFE_SKIP}")

        params: dict[str, str | int] = {"limit": limit, "skip": skip}
        if self._api_key:
            params["api_key"] = self._api_key
        url = f"{OPENFDA_NDC_ENDPOINT}?{urlencode(params)}"
        payload = self._get_json(url)

        meta = payload.get("meta") or {}
        result_meta = meta.get("results") or {}
        raw_results = payload.get("results") or []
        if not isinstance(raw_results, list):
            raise OpenFdaError("openFDA response field 'results' was not a list")

        records = tuple(record for record in raw_results if isinstance(record, dict))
        return OpenFdaPage(
            records=records,
            last_updated=_optional_text(meta.get("last_updated")),
            total_matches=_optional_int(result_meta.get("total")),
            skip=_optional_int(result_meta.get("skip")) or skip,
            limit=_optional_int(result_meta.get("limit")) or limit,
        )

    def iter_pages(
        self, *, record_limit: int, page_size: int = DEFAULT_PAGE_SIZE
    ) -> Iterator[OpenFdaPage]:
        if record_limit <= 0:
            raise ValueError("record_limit must be positive")
        if not 1 <= page_size <= DEFAULT_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {DEFAULT_PAGE_SIZE}")
        if record_limit > MAX_SAFE_SKIP + page_size:
            raise ValueError(
                "API paging mode is intentionally capped at 25,100 source records; "
                "use the official bulk download for a full snapshot"
            )

        remaining = record_limit
        skip = 0
        while remaining > 0:
            current_limit = min(page_size, remaining)
            page = self.fetch_page(limit=current_limit, skip=skip)
            yield page
            received = len(page.records)
            if received == 0:
                break
            remaining -= received
            skip += received
            if received < current_limit:
                break
            if page.total_matches is not None and skip >= page.total_matches:
                break

    def _get_json(self, url: str) -> dict[str, Any]:
        request = Request(
            url,
            headers={"Accept": "application/json", "User-Agent": self._user_agent},
        )
        for attempt in range(self._max_retries + 1):
            try:
                with urlopen(request, timeout=self._timeout_seconds) as response:  # noqa: S310
                    decoded = response.read().decode("utf-8")
                    payload = json.loads(decoded)
                    if not isinstance(payload, dict):
                        raise OpenFdaError("openFDA returned a non-object JSON document")
                    return payload
            except HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code <= 599
                if not retryable or attempt >= self._max_retries:
                    hint = (
                        " Set OPENFDA_API_KEY for reliable repeated ingestion."
                        if exc.code in {401, 403, 429}
                        else ""
                    )
                    raise OpenFdaError(f"openFDA HTTP {exc.code}.{hint}") from exc
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                if attempt >= self._max_retries:
                    raise OpenFdaError(f"openFDA request failed after retries: {exc}") from exc

            time.sleep(min(2**attempt, 8))

        raise AssertionError("unreachable")


@dataclass(frozen=True, slots=True)
class RejectedSourceRecord:
    source_record_id: str
    reason: str
    raw_record: Mapping[str, Any]


@dataclass(slots=True)
class CatalogIngestionReport:
    requested_source_records: int
    source_records_received: int = 0
    source_last_updated: str | None = None
    pages_received: int = 0
    accepted_products: list[Product] = field(default_factory=list)
    rejected_records: list[RejectedSourceRecord] = field(default_factory=list)
    duplicate_products_skipped: int = 0
    raw_records: list[dict[str, Any]] = field(default_factory=list)

    @property
    def accepted_count(self) -> int:
        return len(self.accepted_products)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected_records)


class OpenFdaCatalogIngestor:
    """Build canonical package-level Product records from openFDA NDC data."""

    def __init__(self, client: OpenFdaNdcClient) -> None:
        self._client = client

    def ingest(
        self,
        *,
        record_limit: int,
        page_size: int = DEFAULT_PAGE_SIZE,
        on_page: Callable[[CatalogIngestionReport], None] | None = None,
    ) -> CatalogIngestionReport:
        report = CatalogIngestionReport(requested_source_records=record_limit)
        seen_product_keys: set[str] = set()

        for page in self._client.iter_pages(record_limit=record_limit, page_size=page_size):
            report.pages_received += 1
            report.source_last_updated = page.last_updated or report.source_last_updated
            report.source_records_received += len(page.records)
            report.raw_records.extend(page.records)

            for raw_record in page.records:
                try:
                    products = normalize_openfda_ndc_record(
                        raw_record,
                        source_updated_at=report.source_last_updated,
                    )
                except (ValueError, ValidationError) as exc:
                    report.rejected_records.append(
                        RejectedSourceRecord(
                            source_record_id=source_record_id(raw_record),
                            reason=_compact_error(exc),
                            raw_record=raw_record,
                        )
                    )
                    continue

                for product in products:
                    key = canonical_product_key(product)
                    if key in seen_product_keys:
                        report.duplicate_products_skipped += 1
                        continue
                    seen_product_keys.add(key)
                    report.accepted_products.append(product)

            if on_page is not None:
                on_page(report)

        return report


def normalize_openfda_ndc_record(
    record: Mapping[str, Any], *, source_updated_at: str | None = None
) -> tuple[Product, ...]:
    """Expand one NDC product record into one canonical Product per package.

    NDC's third segment represents package size/type, so package-level expansion
    gives PharmStock saleable SKUs instead of collapsing distinct packages.
    """

    product_ndc = _required_text(record, "product_ndc")
    dosage_form = _required_text(record, "dosage_form")
    ingredients = _parse_ingredients(record.get("active_ingredients"))
    brand_name = _optional_text(record.get("brand_name"))
    generic_name = _optional_text(record.get("generic_name"))
    display_name = brand_name or generic_name or product_ndc
    routes = tuple(_text_list(record.get("route")))
    manufacturer = _optional_text(record.get("labeler_name"))
    openfda = record.get("openfda") if isinstance(record.get("openfda"), Mapping) else {}
    rxcui = _first_text(openfda.get("rxcui")) if isinstance(openfda, Mapping) else None
    source_datetime = _parse_source_datetime(source_updated_at)
    prescription_status = _prescription_status(_optional_text(record.get("product_type")))
    regulatory_status = _regulatory_status(
        _optional_text(record.get("marketing_end_date")),
        source_updated_at=source_updated_at,
    )

    packages = record.get("packaging")
    normalized_packages: list[Mapping[str, Any] | None]
    if isinstance(packages, list) and packages:
        normalized_packages = [package for package in packages if isinstance(package, Mapping)]
        if not normalized_packages:
            normalized_packages = [None]
    else:
        normalized_packages = [None]

    products: list[Product] = []
    for package in normalized_packages:
        package_ndc = _optional_text(package.get("package_ndc")) if package else None
        package_description = _optional_text(package.get("description")) if package else None
        source_id = source_record_id(record, package_ndc=package_ndc)
        stable_id = uuid5(NAMESPACE_URL, f"pharmstock:openfda-ndc:{source_id}")

        products.append(
            Product(
                product_id=stable_id,
                display_name=display_name,
                brand_name=brand_name,
                generic_name=generic_name,
                dosage_form=dosage_form,
                routes=routes,
                active_ingredients=ingredients,
                package_description=package_description,
                manufacturer=manufacturer,
                prescription_status=prescription_status,
                regulatory_status=regulatory_status,
                market_code="US",
                identifiers=ProductIdentifiers(
                    rxnorm_rxcui=rxcui,
                    ndc_product_code=product_ndc,
                    ndc_package_code=package_ndc,
                ),
                source=ProductSource(
                    system="openfda_ndc",
                    record_id=source_id,
                    source_updated_at=source_datetime,
                ),
            )
        )

    return tuple(products)


def canonical_product_key(product: Product) -> str:
    return (
        product.identifiers.ndc_package_code
        or product.identifiers.ndc_product_code
        or str(product.product_id)
    )


def source_record_id(record: Mapping[str, Any], *, package_ndc: str | None = None) -> str:
    base = (
        _optional_text(record.get("product_id"))
        or _optional_text(record.get("product_ndc"))
        or "unknown"
    )
    return f"{base}|{package_ndc}" if package_ndc else base


def _parse_ingredients(value: Any) -> tuple[ActiveIngredient, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("active_ingredients is missing or empty")
    parsed: list[ActiveIngredient] = []
    for ingredient in value:
        if not isinstance(ingredient, Mapping):
            continue
        name = _optional_text(ingredient.get("name"))
        if not name:
            continue
        parsed.append(
            ActiveIngredient(
                name=name,
                strength_text=_optional_text(ingredient.get("strength")),
            )
        )
    if not parsed:
        raise ValueError("active_ingredients contained no usable ingredient names")
    return tuple(parsed)



def _regulatory_status(
    marketing_end_date: str | None, *, source_updated_at: str | None
) -> RegulatoryStatus:
    if not marketing_end_date:
        return RegulatoryStatus.ACTIVE
    end_date = _parse_compact_date(marketing_end_date)
    if end_date is None:
        return RegulatoryStatus.UNKNOWN
    reference_date = _parse_compact_date(source_updated_at) if source_updated_at else None
    reference_date = reference_date or datetime.now(UTC).date()
    return RegulatoryStatus.INACTIVE if end_date <= reference_date else RegulatoryStatus.ACTIVE


def _parse_compact_date(value: str | None) -> date | None:
    if not value:
        return None
    compact = value.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(compact, fmt).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(compact.replace("Z", "+00:00")).date()
    except ValueError:
        return None

def _prescription_status(product_type: str | None) -> PrescriptionStatus:
    normalized = (product_type or "").casefold()
    if "otc" in normalized or "over the counter" in normalized:
        return PrescriptionStatus.OTC
    if "prescription" in normalized:
        return PrescriptionStatus.PRESCRIPTION
    return PrescriptionStatus.UNKNOWN


def _required_text(record: Mapping[str, Any], field_name: str) -> str:
    value = _optional_text(record.get(field_name))
    if not value:
        raise ValueError(f"{field_name} is missing")
    return value


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_text(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            text = _optional_text(item)
            if text:
                return text
        return None
    return _optional_text(value)


def _text_list(value: Any) -> Iterable[str]:
    if isinstance(value, list):
        for item in value:
            text = _optional_text(item)
            if text:
                yield text
    else:
        text = _optional_text(value)
        if text:
            yield text


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_source_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    compact = value.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(compact, fmt).replace(tzinfo=UTC)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(compact.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _compact_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        errors = exc.errors(include_url=False)
        if errors:
            first = errors[0]
            location = ".".join(str(part) for part in first.get("loc", ()))
            prefix = f"{location}: " if location else ""
            return f"{prefix}{first.get('msg', 'validation error')}"
    return str(exc).replace("\n", " ")[:500]
