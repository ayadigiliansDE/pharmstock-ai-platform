"""Build the Stage 7A Egypt-oriented pharmaceutical and price master locally."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from pharmstock.ingestion.egypt_market_drugs import (
    DEFAULT_EGYPT_MARKET_SOURCE_URL,
    DEFAULT_MIN_ACCEPTED_PRODUCTS,
    DEFAULT_SOURCE_LICENSE,
    DEFAULT_SOURCE_REPOSITORY_URL,
    DEFAULT_SOURCE_SNAPSHOT_LABEL,
    EDA_VERIFICATION_FIELDS,
    OFFICIAL_AUTHORITY,
    OFFICIAL_REGISTRY,
    PRICE_HISTORY_FIELDS,
    PRODUCT_MASTER_FIELDS,
    PROVENANCE_CLASS,
    SOURCE_SYSTEM,
    download_or_copy_snapshot,
    file_sha256,
    ingest_egypt_market_csv,
    quality_summary,
    validate_report,
    write_csv,
)

DEFAULT_OUTPUT = Path("artifacts/stage7a")
DEFAULT_CACHE = Path("artifacts/source_cache/egyptian-drugs-2026-06.csv")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def _eda_contract() -> dict[str, object]:
    return {
        "authority": OFFICIAL_AUTHORITY,
        "registry": OFFICIAL_REGISTRY,
        "automation_policy": (
            "Do not bypass EDDB verification-code/CAPTCHA controls. Import an official export or "
            "authorized API response when one becomes available."
        ),
        "official_reference_fields": [
            "name",
            "product_type",
            "dosage_form",
            "shelf_life",
            "route",
            "strength",
            "pack_unit_and_details",
            "applicant",
            "company_name",
            "registration_number",
            "market_type",
            "registration_type",
            "registration_expiry_date",
            "license_status",
            "price_status",
            "physical_character",
            "storage_condition",
            "registration_date",
            "gtin",
        ],
        "pharma_data_hub_fields_of_interest": [
            "gtin",
            "package_specification",
            "priced_package",
            "manufacturer_roles",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a real/public Egypt-oriented pharmaceutical master and price snapshot"
    )
    parser.add_argument("--source-url", default=DEFAULT_EGYPT_MARKET_SOURCE_URL)
    parser.add_argument("--source-file", type=Path)
    parser.add_argument("--snapshot-label", default=DEFAULT_SOURCE_SNAPSHOT_LABEL)
    parser.add_argument("--min-products", type=int, default=DEFAULT_MIN_ACCEPTED_PRODUCTS)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    if args.min_products <= 0:
        raise SystemExit("--min-products must be positive")

    observed_at = datetime.now(UTC)
    source_path = download_or_copy_snapshot(
        args.cache,
        source_url=args.source_url,
        offline_file=args.source_file,
        refresh=args.refresh,
    )
    report = ingest_egypt_market_csv(source_path)
    issues = validate_report(report, min_accepted_products=args.min_products)
    if issues:
        raise SystemExit("Stage 7A validation failed: " + "; ".join(issues))

    output = args.output
    output.mkdir(parents=True, exist_ok=True)

    product_master = output / "egypt_product_master.csv"
    price_history = output / "product_price_history.csv"
    verification_queue = output / "eda_verification_queue.csv"
    rejects = output / "rejected_market_records.csv"
    quality_path = output / "data_quality_report.json"
    manifest_path = output / "source_snapshot_manifest.json"
    eda_contract_path = output / "eda_reference_contract.json"

    write_csv(
        product_master,
        PRODUCT_MASTER_FIELDS,
        [product.product_row(snapshot_label=args.snapshot_label) for product in report.products],
    )
    write_csv(
        price_history,
        PRICE_HISTORY_FIELDS,
        [
            product.price_row(snapshot_label=args.snapshot_label, observed_at=observed_at)
            for product in report.products
        ],
    )
    write_csv(
        verification_queue,
        EDA_VERIFICATION_FIELDS,
        [product.verification_row() for product in report.products],
    )

    reject_fields = (
        "source_record_number",
        "reason",
        "trade_name_en",
        *(
            "commercial_name_ar",
            "scientific_name",
            "manufacturer",
            "drug_class",
            "route",
            "price_egp",
        ),
    )
    reject_rows: list[dict[str, object]] = []
    for item in report.rejected_rows:
        reject_rows.append(
            {
                "source_record_number": item.source_record_number,
                "reason": item.reason,
                "trade_name_en": item.trade_name_en,
                "commercial_name_ar": item.raw_row.get("commercial_name_ar", ""),
                "scientific_name": item.raw_row.get("scientific_name", ""),
                "manufacturer": item.raw_row.get("manufacturer", ""),
                "drug_class": item.raw_row.get("drug_class", ""),
                "route": item.raw_row.get("route", ""),
                "price_egp": item.raw_row.get("price_egp", ""),
            }
        )
    write_csv(rejects, reject_fields, reject_rows)

    quality = quality_summary(report)
    _write_json(quality_path, quality)
    _write_json(eda_contract_path, _eda_contract())
    manifest = {
        "stage": "7A",
        "market": "EG",
        "source_classification": PROVENANCE_CLASS,
        "source_system": SOURCE_SYSTEM,
        "source_url": args.source_url,
        "source_repository_url": DEFAULT_SOURCE_REPOSITORY_URL,
        "source_license": DEFAULT_SOURCE_LICENSE,
        "source_snapshot_label": args.snapshot_label,
        "source_file": str(source_path),
        "source_sha256": file_sha256(source_path),
        "source_rows": report.source_rows,
        "accepted_products": report.accepted_count,
        "rejected_rows": report.rejected_count,
        "duplicate_rows_skipped": report.duplicate_rows_skipped,
        "observed_at": observed_at.isoformat(),
        "official_authority": OFFICIAL_AUTHORITY,
        "official_registry": OFFICIAL_REGISTRY,
        "official_registration_verified_rows": 0,
        "official_price_verified_rows": 0,
        "synthetic_product_rows": 0,
        "cloud_mutation_performed": False,
    }
    _write_json(manifest_path, manifest)
    (output / "_SUCCESS").write_text("STAGE_7A_STATUS=PASS\n", encoding="utf-8")

    print("=== PharmStock V2 / Stage 7A Egyptian Pharmaceutical Master ===")
    print(f"Source classification:   {PROVENANCE_CLASS}")
    print(f"Source snapshot:         {args.snapshot_label}")
    print(f"Source rows:             {report.source_rows:,}")
    print(f"Accepted medicines:      {report.accepted_count:,}")
    print(f"Rejected/audit rows:     {report.rejected_count:,}")
    print(f"Duplicates skipped:      {report.duplicate_rows_skipped:,}")
    print(f"Retail price rows:       {report.accepted_count:,}")
    print("Market/currency:         EG / EGP")
    print("Synthetic product rows:  0")
    print("EDA verified rows:       0 (verification queue generated)")
    print("Cloud mutation:          NO")
    print("\nGenerated files:")
    for path in (
        product_master,
        price_history,
        verification_queue,
        rejects,
        quality_path,
        manifest_path,
        eda_contract_path,
    ):
        print(f"  {path}")
    print("\nSTAGE_7A_STATUS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
