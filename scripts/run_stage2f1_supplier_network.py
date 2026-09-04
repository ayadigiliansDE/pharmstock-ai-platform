"""Stage 2F.1: run procurement against the scaled synthetic supplier ecosystem."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pharmstock.simulation import (
    SupplierNetworkPolicy,
    build_scaled_supplier_network,
    export_procurement_cycle,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Stage 2F.1 supplier-network scaling and procurement"
    )
    parser.add_argument("--stage2e", type=Path, default=Path("artifacts/stage2e"))
    parser.add_argument("--seed", type=int, default=20260822)
    parser.add_argument("--output", type=Path, default=Path("artifacts/stage2f1"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not (args.stage2e / "_SUCCESS").exists():
        print("STAGE_2F1_STATUS=FAIL")
        print(f"Completed Stage 2E dataset not found at: {args.stage2e.resolve()}")
        print("Run: python scripts\\run_checkpoint.py 2e")
        return 2

    network_policy = SupplierNetworkPolicy()
    suppliers = build_scaled_supplier_network(seed=args.seed, policy=network_policy)
    type_counts: dict[str, int] = {}
    for supplier in suppliers:
        key = supplier.supplier_type.value
        type_counts[key] = type_counts.get(key, 0) + 1

    print("=== PharmStock V2 / Stage 2F.1 Supplier Network Scaling ===")
    print(f"Stage 2E input:           {args.stage2e.resolve()}")
    print(f"Supplier-network seed:    {args.seed}")
    print(f"Synthetic suppliers:      {len(suppliers):,}")
    print(f"Preferred panel / branch: {network_policy.preferred_supplier_panel_size}")
    print("Supplier identities:      SYNTHETIC")
    print("Service metrics:          SYNTHETIC")
    print("Money / costs:            NOT SIMULATED")
    print("Supplier selection:       GEO + ASSORTMENT + RELIABILITY + LEAD TIME + CAPACITY")
    print("\nSupplier types:")
    for supplier_type, count in sorted(type_counts.items()):
        print(f"  {supplier_type:<24} {count:>4,}")
    print("\nCreating ranked supplier panels + POs + receipts...\n")

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
        supplier_network_policy=network_policy,
        stage_label="2F.1",
        on_branch=progress,
    )
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    print("\nScaled procurement cycle:")
    print(f"  Branches:               {result.branch_count:,}")
    print(f"  Supplier network:       {result.suppliers:,}")
    print(f"  Suppliers actually used:{result.suppliers_used:>7,}")
    print(f"  Purchase orders:        {result.purchase_orders:,}")
    print(f"  Purchase-order lines:   {result.purchase_order_lines:,}")
    print(f"  Ordered units:          {result.ordered_units:,}")
    print(f"  Received units:         {result.received_units:,}")
    print(f"  Deferred units:         {result.deferred_units:,}")
    print(f"  Restock movements:      {result.restock_movements:,}")
    print(f"  Network mode:           {manifest['supplier_network_mode']}")
    print("\nGenerated files:")
    print(f"  {result.supplier_master_path}")
    print(f"  {result.supplier_utilization_path}")
    print(f"  {result.branch_supplier_panel_path}")
    print(f"  {result.branch_kpi_path}")
    print(f"  {result.output_dir / 'procurement_backlog.csv'}")
    print(f"  {result.manifest_path}")
    print(f"  {result.success_marker_path}")
    print("\nSTAGE_2F1_STATUS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
