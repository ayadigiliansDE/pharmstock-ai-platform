"""Stage 2F: create purchase orders, deliveries and restock batches from Stage 2E."""

from __future__ import annotations

import argparse
from pathlib import Path

from pharmstock.simulation import export_procurement_cycle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one end-of-cycle synthetic procurement and replenishment pass"
    )
    parser.add_argument("--stage2e", type=Path, default=Path("artifacts/stage2e"))
    parser.add_argument("--seed", type=int, default=20260822)
    parser.add_argument("--output", type=Path, default=Path("artifacts/stage2f"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not (args.stage2e / "_SUCCESS").exists():
        print("STAGE_2F_STATUS=FAIL")
        print(f"Completed Stage 2E dataset not found at: {args.stage2e.resolve()}")
        print("Run: python scripts\\run_checkpoint.py 2e")
        return 2

    print("=== PharmStock V2 / Stage 2F Procurement & Replenishment ===")
    print(f"Stage 2E input:           {args.stage2e.resolve()}")
    print(f"Procurement seed:         {args.seed}")
    print("Supplier master:          SYNTHETIC")
    print("Supplier lead times:      SYNTHETIC")
    print("Money / costs:            NOT SIMULATED")
    print("Timing mode:              END-OF-CYCLE AFTER STAGE 2E")
    print("Capacity rule:            BRANCH STORAGE CAPACITY ENFORCED")
    print("Inventory memory mode:    ONE BRANCH AT A TIME")
    print("Creating POs + receiving stock...\n")

    def progress(index, total, branch_code, purchase_orders, received_units, deferred_units):
        if index <= 5 or index == total or index % 25 == 0:
            print(
                f"  branch {index:>4}/{total:<4} | {branch_code} | "
                f"POs={purchase_orders:>3,} | received={received_units:>6,} | "
                f"deferred={deferred_units:>5,}"
            )

    result = export_procurement_cycle(
        stage2e_dir=args.stage2e,
        output_dir=args.output,
        seed=args.seed,
        on_branch=progress,
    )

    print("\nProcurement cycle:")
    print(f"  Branches:               {result.branch_count:,}")
    print(f"  Synthetic suppliers:    {result.suppliers:,}")
    print(f"  Purchase orders:        {result.purchase_orders:,}")
    print(f"  Purchase-order lines:   {result.purchase_order_lines:,}")
    print(f"  Ordered units:          {result.ordered_units:,}")
    print(f"  Received units:         {result.received_units:,}")
    print(f"  Deferred units:         {result.deferred_units:,}")
    print(f"  Restock movements:      {result.restock_movements:,}")
    print(f"  Output partitions:      {result.partition_count:,}")
    print("\nGenerated locations:")
    print(f"  {result.supplier_master_path}")
    for name in (
        "purchase_orders",
        "purchase_order_lines",
        "goods_receipts",
        "goods_receipt_lines",
        "restock_movements",
        "ending_inventory",
        "ending_batches",
    ):
        print(f"  {result.output_dir / name}")
    print(f"  {result.output_dir / 'procurement_backlog.csv'}")
    print(f"  {result.branch_kpi_path}")
    print(f"  {result.manifest_path}")
    print(f"  {result.success_marker_path}")
    print("\nSTAGE_2F_STATUS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
