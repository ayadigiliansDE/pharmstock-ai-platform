from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pharmstock.ingestion.egypt_market_drugs import (
    OFFICIAL_VERIFICATION_STATE,
    PROVENANCE_CLASS,
    EgyptMarketDrugError,
    ingest_egypt_market_csv,
    normalize_egypt_market_row,
    quality_summary,
    validate_report,
)

FIXTURE = Path(__file__).parent / "fixtures" / "egypt_market_drugs_sample.csv"


def _row(**overrides: str) -> dict[str, str]:
    row = {
        "commercial_name_en": "ABIMOL 500 MG 20 TAB.",
        "commercial_name_ar": "أبيمول",
        "scientific_name": "PARACETAMOL(ACETAMINOPHEN)",
        "manufacturer": "GLAXO SMITHKLINE",
        "drug_class": "ANTIPYRETIC",
        "route": "ORAL.SOLID",
        "price_egp": "24.0",
    }
    row.update(overrides)
    return row


def test_normalized_market_product_is_egypt_public_market_not_synthetic() -> None:
    product = normalize_egypt_market_row(_row(), source_record_number=1)
    row = product.product_row(snapshot_label="2026-06")

    assert row["market_code"] == "EG"
    assert row["currency"] == "EGP"
    assert row["provenance_class"] == PROVENANCE_CLASS
    assert row["synthetic_record"] == "false"
    assert row["official_registration_verified"] == "false"
    assert row["official_verification_state"] == OFFICIAL_VERIFICATION_STATE


def test_product_identity_is_deterministic_for_same_market_facts() -> None:
    left = normalize_egypt_market_row(_row(), source_record_number=1)
    right = normalize_egypt_market_row(_row(), source_record_number=999)
    assert left.product_id == right.product_id
    assert left.market_product_key == right.market_product_key


def test_price_history_is_explicitly_market_snapshot_not_official_price() -> None:
    product = normalize_egypt_market_row(_row(), source_record_number=1)
    price = product.price_row(
        snapshot_label="2026-06",
        observed_at=datetime(2026, 8, 23, tzinfo=UTC),
    )
    assert price["price_egp"] == "24.00"
    assert price["price_type"] == "retail_market_snapshot"
    assert price["official_price_verified"] == "false"


def test_cancelled_and_illegal_import_markers_are_not_promoted() -> None:
    with pytest.raises(ValueError, match="CANCELLED"):
        normalize_egypt_market_row(
            _row(commercial_name_en="EXAMPLE (CANCELLED)"),
            source_record_number=1,
        )
    with pytest.raises(ValueError, match="ILLEGAL IMPORT"):
        normalize_egypt_market_row(
            _row(commercial_name_en="EXAMPLE (ILLEGAL IMPORT)"),
            source_record_number=1,
        )


def test_missing_scientific_composition_stays_in_audit_not_medicine_master() -> None:
    with pytest.raises(ValueError, match="missing_scientific_name"):
        normalize_egypt_market_row(_row(scientific_name=""), source_record_number=1)


def test_non_positive_price_is_rejected() -> None:
    with pytest.raises(ValueError, match="non_positive_price"):
        normalize_egypt_market_row(_row(price_egp="0"), source_record_number=1)


def test_fixture_ingestion_deduplicates_and_audits_low_confidence_rows() -> None:
    report = ingest_egypt_market_csv(FIXTURE)
    assert report.source_rows == 8
    assert report.accepted_count == 3
    assert report.duplicate_rows_skipped == 1
    assert report.rejected_count == 4
    assert report.exclusion_reasons["missing_scientific_name"] == 1


def test_quality_summary_has_full_price_and_scientific_coverage_for_accepted_master() -> None:
    summary = quality_summary(ingest_egypt_market_csv(FIXTURE))
    assert summary["accepted_products"] == 3
    assert summary["price_coverage_pct"] == 100.0
    assert summary["scientific_name_coverage_pct"] == 100.0
    assert summary["synthetic_product_rows"] == 0
    assert summary["eda_verification_required_rows"] == 3


def test_report_validation_enforces_scale_threshold() -> None:
    report = ingest_egypt_market_csv(FIXTURE)
    issues = validate_report(report, min_accepted_products=4)
    assert any("below required" in issue for issue in issues)
    assert validate_report(report, min_accepted_products=3) == ()


def test_unknown_route_is_allowed_but_normalized() -> None:
    product = normalize_egypt_market_row(_row(route="."), source_record_number=1)
    assert product.route == "UNKNOWN"


def test_verification_queue_never_fabricates_eda_identifiers() -> None:
    product = normalize_egypt_market_row(_row(), source_record_number=1)
    verification = product.verification_row()
    assert verification["eda_registration_number"] == ""
    assert verification["gtin"] == ""
    assert verification["verification_status"] == OFFICIAL_VERIFICATION_STATE


def test_source_schema_mismatch_fails_loudly(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "price"])
        writer.writeheader()
        writer.writerow({"name": "x", "price": "1"})
    with pytest.raises(EgyptMarketDrugError, match="missing columns"):
        ingest_egypt_market_csv(path)
