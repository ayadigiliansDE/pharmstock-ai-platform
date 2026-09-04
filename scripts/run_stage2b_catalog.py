"""Download real openFDA NDC records and build the Stage 2B canonical catalog."""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from pharmstock.domain.product import Product
from pharmstock.ingestion.openfda_ndc import (
    DEFAULT_PAGE_SIZE,
    OpenFdaCatalogIngestor,
    OpenFdaError,
    OpenFdaNdcClient,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a real package-level drug catalog from the official openFDA NDC API"
    )
    parser.add_argument("--records", type=int, default=500, help="Number of NDC source records")
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help=f"Source records per API call (max {DEFAULT_PAGE_SIZE})",
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/stage2b"))
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.records <= 0:
        raise SystemExit("--records must be positive")

    client = OpenFdaNdcClient(
        api_key=os.getenv("OPENFDA_API_KEY"),
        timeout_seconds=args.timeout,
    )
    ingestor = OpenFdaCatalogIngestor(client)

    print("=== PharmStock V2 / Stage 2B ===")
    print("Source:            openFDA NDC Directory (official U.S. dataset)")
    print(f"Requested records: {args.records:,}")
    print(f"Page size:         {args.page_size}")
    print("Downloading + normalizing...\n")

    try:
        def show_progress(current_report) -> None:
            print(
                f"  page {current_report.pages_received:>3}: "
                f"source={current_report.source_records_received:>6,} | "
                f"canonical={current_report.accepted_count:>6,} | "
                f"rejected={current_report.rejected_count:>4,}"
            )

        report = ingestor.ingest(
            record_limit=args.records,
            page_size=args.page_size,
            on_page=show_progress,
        )
    except OpenFdaError as exc:
        print(f"STAGE_2B_STATUS=FAIL\nReason: {exc}")
        return 2

    output_dir: Path = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_path = output_dir / "openfda_ndc_raw.jsonl"
    catalog_csv_path = output_dir / "drug_catalog.csv"
    catalog_json_path = output_dir / "drug_catalog.json"
    rejects_path = output_dir / "rejected_records.jsonl"
    summary_path = output_dir / "ingestion_summary.json"

    _write_jsonl(raw_path, report.raw_records)
    _write_catalog_csv(catalog_csv_path, report.accepted_products)
    _write_json(
        catalog_json_path,
        [product.model_dump(mode="json") for product in report.accepted_products],
    )
    _write_jsonl(
        rejects_path,
        [
            {
                "source_record_id": item.source_record_id,
                "reason": item.reason,
                "raw_record": dict(item.raw_record),
            }
            for item in report.rejected_records
        ],
    )

    dosage_forms = Counter(product.dosage_form for product in report.accepted_products)
    prescription_status = Counter(
        product.prescription_status.value for product in report.accepted_products
    )
    summary: dict[str, Any] = {
        "stage": "2B",
        "source": "openFDA NDC Directory",
        "source_market": "US",
        "source_last_updated": report.source_last_updated,
        "requested_source_records": report.requested_source_records,
        "source_records_received": report.source_records_received,
        "pages_received": report.pages_received,
        "accepted_package_products": report.accepted_count,
        "rejected_source_records": report.rejected_count,
        "duplicate_products_skipped": report.duplicate_products_skipped,
        "unique_ndc_product_codes": len(
            {
                p.identifiers.ndc_product_code
                for p in report.accepted_products
                if p.identifiers.ndc_product_code
            }
        ),
        "unique_ndc_package_codes": len(
            {
                p.identifiers.ndc_package_code
                for p in report.accepted_products
                if p.identifiers.ndc_package_code
            }
        ),
        "top_dosage_forms": dosage_forms.most_common(10),
        "prescription_status": dict(sorted(prescription_status.items())),
    }
    _write_json(summary_path, summary)

    print(f"Source last update:       {report.source_last_updated or 'not supplied'}")
    print(f"Source records received:  {report.source_records_received:,}")
    print(f"Canonical package SKUs:   {report.accepted_count:,}")
    print(f"Rejected source records:  {report.rejected_count:,}")
    print(f"Duplicates skipped:       {report.duplicate_products_skipped:,}")
    print(f"API pages received:       {report.pages_received:,}\n")

    print("Generated files:")
    for path in (raw_path, catalog_csv_path, catalog_json_path, rejects_path, summary_path):
        print(f"  {path}")

    if report.accepted_products:
        print("\nSample canonical products:")
        for product in report.accepted_products[:5]:
            ndc_code = (
                product.identifiers.ndc_package_code
                or product.identifiers.ndc_product_code
            )
            print(f"  {product.display_name} | {product.dosage_form} | NDC {ndc_code}")

    print("\nSTAGE_2B_STATUS=PASS")
    return 0


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _write_catalog_csv(path: Path, products: list[Product]) -> None:
    fieldnames = [
        "product_id",
        "display_name",
        "brand_name",
        "generic_name",
        "dosage_form",
        "routes",
        "active_ingredients",
        "package_description",
        "manufacturer",
        "prescription_status",
        "regulatory_status",
        "market_code",
        "rxnorm_rxcui",
        "ndc_product_code",
        "ndc_package_code",
        "source_system",
        "source_record_id",
        "source_updated_at",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for product in products:
            writer.writerow(
                {
                    "product_id": str(product.product_id),
                    "display_name": product.display_name,
                    "brand_name": product.brand_name or "",
                    "generic_name": product.generic_name or "",
                    "dosage_form": product.dosage_form,
                    "routes": " | ".join(product.routes),
                    "active_ingredients": " | ".join(
                        f"{item.name} {item.strength_text or ''}".strip()
                        for item in product.active_ingredients
                    ),
                    "package_description": product.package_description or "",
                    "manufacturer": product.manufacturer or "",
                    "prescription_status": product.prescription_status.value,
                    "regulatory_status": product.regulatory_status.value,
                    "market_code": product.market_code,
                    "rxnorm_rxcui": product.identifiers.rxnorm_rxcui or "",
                    "ndc_product_code": product.identifiers.ndc_product_code or "",
                    "ndc_package_code": product.identifiers.ndc_package_code or "",
                    "source_system": product.source.system,
                    "source_record_id": product.source.record_id,
                    "source_updated_at": product.source.source_updated_at.isoformat()
                    if product.source.source_updated_at
                    else "",
                }
            )


if __name__ == "__main__":
    raise SystemExit(main())
