"""Stage 2D: bounded-memory, partitioned inventory generation."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from pharmstock.domain import Product
from pharmstock.simulation import (
    InitialInventoryGenerator,
    PharmacyNetworkGenerator,
    export_initial_inventory_streaming,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate large inventory as partitioned CSV files"
    )
    parser.add_argument("--catalog", type=Path, required=True, help="Stage 2B drug_catalog.json")
    parser.add_argument("--pharmacies", type=int, default=25)
    parser.add_argument("--branches-per-part", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260822)
    parser.add_argument("--reference-date", type=date.fromisoformat, default=date(2026, 8, 22))
    parser.add_argument("--output", type=Path, default=Path("artifacts/stage2d"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.pharmacies <= 0:
        raise SystemExit("--pharmacies must be positive")
    if args.branches_per_part <= 0:
        raise SystemExit("--branches-per-part must be positive")
    if not args.catalog.exists():
        print(f"STAGE_2D_STATUS=FAIL\nCatalog not found: {args.catalog}")
        print("Run Stage 2B first to generate drug_catalog.json.")
        return 2

    raw = json.loads(args.catalog.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit("catalog JSON must contain a list of products")
    products = [Product.model_validate(item) for item in raw]
    network = PharmacyNetworkGenerator(seed=args.seed).generate(args.pharmacies)

    print("=== PharmStock V2 / Stage 2D Scale Hardening ===")
    print(f"Catalog file:            {args.catalog.resolve()}")
    print(f"Catalog products:        {len(products):,}")
    print(f"Pharmacy branches:       {len(network.branches):,}")
    print(f"Branches / partition:    {args.branches_per_part:,}")
    print(f"Reference date:          {args.reference_date.isoformat()}")
    print("Memory mode:             ONE BRANCH AT A TIME")
    print("Output mode:             PARTITIONED CSV")
    print("Prices generated:        NO")
    print("Generating + writing...\n")

    def progress(index: int, total: int, summary) -> None:
        if index <= 5 or index == total or index % 25 == 0:
            print(
                f"  branch {index:>4}/{total:<4} | {summary.branch_code} | "
                f"skus={summary.generated_assortment_skus:>5,} | "
                f"units={summary.generated_stock_units:>7,}"
            )

    result = export_initial_inventory_streaming(
        output_dir=args.output,
        generator=InitialInventoryGenerator(
            seed=args.seed,
            reference_date=args.reference_date,
        ),
        network=network,
        products=products,
        branches_per_partition=args.branches_per_part,
        on_branch=progress,
    )

    print("\nStreaming export:")
    print(f"  Branches:               {result.branch_count:,}")
    print(f"  Branch-product rows:    {result.inventory_rows:,}")
    print(f"  Batch rows:             {result.batch_rows:,}")
    print(f"  Initial stock units:    {result.total_initial_stock_units:,}")
    print(f"  Output partitions:      {result.partition_count:,}")
    print("\nGenerated locations:")
    print(f"  {result.output_dir / 'inventory'}")
    print(f"  {result.output_dir / 'batches'}")
    print(f"  {result.branch_summary_path}")
    print(f"  {result.manifest_path}")
    print(f"  {result.success_marker_path}")
    print("\nSTAGE_2D_SCALE_STATUS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
