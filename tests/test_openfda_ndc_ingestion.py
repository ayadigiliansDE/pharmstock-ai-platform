from __future__ import annotations

import json
from pathlib import Path

import pytest

from pharmstock.domain.product import PrescriptionStatus, RegulatoryStatus
from pharmstock.ingestion.openfda_ndc import (
    CatalogIngestionReport,
    OpenFdaCatalogIngestor,
    OpenFdaNdcClient,
    OpenFdaPage,
    canonical_product_key,
    normalize_openfda_ndc_record,
)

FIXTURE = Path(__file__).parent / "fixtures" / "openfda_ndc_sample.json"


def load_sample() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_one_source_product_expands_to_package_level_skus() -> None:
    record = load_sample()["results"][0]
    products = normalize_openfda_ndc_record(record, source_updated_at="2026-07-23")

    assert len(products) == 2
    assert {p.identifiers.ndc_package_code for p in products} == {
        "12345-678-01",
        "12345-678-02",
    }


def test_openfda_product_maps_to_us_market_and_source_lineage() -> None:
    product = normalize_openfda_ndc_record(load_sample()["results"][0])[0]

    assert product.market_code == "US"
    assert product.source.system == "openfda_ndc"
    assert product.identifiers.ndc_product_code == "12345-678"
    assert product.identifiers.rxnorm_rxcui == "123456"


def test_prescription_status_and_active_regulatory_status_are_derived() -> None:
    product = normalize_openfda_ndc_record(load_sample()["results"][0])[0]

    assert product.prescription_status is PrescriptionStatus.PRESCRIPTION
    assert product.regulatory_status is RegulatoryStatus.ACTIVE


def test_routes_are_normalized_by_domain_model() -> None:
    product = normalize_openfda_ndc_record(load_sample()["results"][0])[0]
    assert product.routes == ("oral",)


def test_product_ids_are_deterministic_for_same_source_package() -> None:
    record = load_sample()["results"][0]
    left = normalize_openfda_ndc_record(record)[0]
    right = normalize_openfda_ndc_record(record)[0]
    assert left.product_id == right.product_id


def test_missing_ingredients_rejects_source_record() -> None:
    with pytest.raises(ValueError, match="active_ingredients"):
        normalize_openfda_ndc_record(load_sample()["results"][1])


def test_past_marketing_end_date_marks_product_inactive() -> None:
    record = dict(load_sample()["results"][0])
    record["marketing_end_date"] = "20250101"
    product = normalize_openfda_ndc_record(record, source_updated_at="2026-07-23")[0]
    assert product.regulatory_status is RegulatoryStatus.INACTIVE


def test_future_marketing_end_date_remains_active() -> None:
    record = dict(load_sample()["results"][0])
    record["marketing_end_date"] = "20270101"
    product = normalize_openfda_ndc_record(record, source_updated_at="2026-07-23")[0]
    assert product.regulatory_status is RegulatoryStatus.ACTIVE


def test_client_enforces_conservative_ndc_page_size() -> None:
    client = OpenFdaNdcClient()
    with pytest.raises(ValueError, match="limit"):
        client.fetch_page(limit=101)


class FakeClient:
    def __init__(self) -> None:
        payload = load_sample()
        self.page = OpenFdaPage(
            records=tuple(payload["results"]),
            last_updated=payload["meta"]["last_updated"],
            total_matches=2,
            skip=0,
            limit=2,
        )

    def iter_pages(self, *, record_limit: int, page_size: int):
        assert record_limit == 2
        assert page_size == 2
        yield self.page


def test_ingestor_counts_accepted_package_skus_and_rejects() -> None:
    report = OpenFdaCatalogIngestor(FakeClient()).ingest(  # type: ignore[arg-type]
        record_limit=2, page_size=2
    )

    assert isinstance(report, CatalogIngestionReport)
    assert report.source_records_received == 2
    assert report.accepted_count == 2
    assert report.rejected_count == 1
    assert report.source_last_updated == "2026-07-23"


def test_canonical_key_prefers_package_ndc() -> None:
    product = normalize_openfda_ndc_record(load_sample()["results"][0])[0]
    assert canonical_product_key(product) == "12345-678-01"
