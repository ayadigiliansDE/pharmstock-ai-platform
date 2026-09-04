"""Build Stage 2C synthetic branch assortment, initial stock and expiry batches."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pharmstock.domain import Product
from pharmstock.simulation import (
    InitialInventoryGenerator,
    PharmacyNetworkGenerator,
    export_initial_inventory,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate branch assortments and initial inventory"
    )
    parser.add_argument("--catalog", type=Path, required=True, help="Stage 2B drug_catalog.json")
    parser.add_argument("--pharmacies", type=int, default=25)
    parser.add_argument("--seed", type=int, default=20260822)
    parser.add_argument("--output", type=Path, default=Path("artifacts/stage2c"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.pharmacies <= 0:
        raise SystemExit("--pharmacies must be positive")
    if not args.catalog.exists():
        print(f"STAGE_2C_STATUS=FAIL\nCatalog not found: {args.catalog}")
        print("Run Stage 2B first to generate drug_catalog.json.")
        return 2

    raw = json.loads(args.catalog.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit("catalog JSON must contain a list of products")
    products = [Product.model_validate(item) for item in raw]
    network = PharmacyNetworkGenerator(seed=args.seed).generate(args.pharmacies)

    print("=== PharmStock V2 / Stage 2C ===")
    print(f"Catalog file:       {args.catalog.resolve()}")
    print(f"Catalog products:   {len(products):,}")
    print(f"Pharmacy branches:  {len(network.branches):,}")
    print(f"Seed:               {args.seed}")
    print("Mapping status:     synthetic_cross_market_mapping")
    print("Prices generated:   NO")
    print("Generating assortment + stock + batches...\n")

    def progress(index: int, total: int, summary) -> None:
        if index <= 5 or index == total or index % 25 == 0:
            print(
                f"  branch {index:>4}/{total:<4} | {summary.branch_code} | "
                f"skus={summary.generated_assortment_skus:>5,} | "
                f"units={summary.generated_stock_units:>7,}"
            )

    generated = InitialInventoryGenerator(seed=args.seed).generate(
        network=network,
        products=products,
        on_branch=progress,
    )
    paths = export_initial_inventory(args.output.resolve(), generated)
    summary = generated.summary()

    print("\nGenerated inventory:")
    print(f"  Branch-product rows: {summary['branch_product_inventory_rows']:,}")
    print(f"  Batch rows:          {summary['inventory_batch_rows']:,}")
    print(f"  Initial stock units: {summary['total_initial_stock_units']:,}")
    print(f"  Avg SKUs / branch:   {summary['average_skus_per_branch']:,}")
    print("\nGenerated files:")
    for path in paths:
        print(f"  {path}")
    print("\nSTAGE_2C_STATUS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
