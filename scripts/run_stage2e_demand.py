"""Stage 2E: replay structured synthetic unit demand against Stage 2D stock."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from pharmstock.simulation import export_demand_simulation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulate multi-day unit demand, FEFO fulfillment and stockouts"
    )
    parser.add_argument("--stage2d", type=Path, default=Path("artifacts/stage2d"))
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2026, 8, 22))
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--seed", type=int, default=20260822)
    parser.add_argument("--output", type=Path, default=Path("artifacts/stage2e"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.days <= 0:
        raise SystemExit("--days must be positive")
    if not (args.stage2d / "_SUCCESS").exists():
        print("STAGE_2E_STATUS=FAIL")
        print(f"Completed Stage 2D dataset not found at: {args.stage2d.resolve()}")
        print("Run: python scripts\\run_checkpoint.py 2d")
        return 2

    print("=== PharmStock V2 / Stage 2E Demand & Unit Sales ===")
    print(f"Stage 2D input:          {args.stage2d.resolve()}")
    print(f"Simulation start:        {args.start_date.isoformat()}")
    print(f"Simulation days:         {args.days}")
    print(f"Demand seed:             {args.seed}")
    print("Demand model:            SYNTHETIC / STRUCTURED")
    print("Money / prices:          NOT SIMULATED")
    print("Inventory memory mode:   ONE BRANCH AT A TIME")
    print("Fulfillment rule:        FEFO")
    print("Simulating...\n")

    def progress(index, total, branch, demand_lines, fulfilled_units, lost_units):
        if index <= 5 or index == total or index % 25 == 0:
            print(
                f"  branch {index:>4}/{total:<4} | {branch.branch_code} | "
                f"lines={demand_lines:>6,} | sold_units={fulfilled_units:>7,} | "
                f"lost_units={lost_units:>6,}"
            )

    result = export_demand_simulation(
        stage2d_dir=args.stage2d,
        output_dir=args.output,
        start_date=args.start_date,
        days=args.days,
        seed=args.seed,
        on_branch=progress,
    )

    fulfillment_rate = (
        result.fulfilled_units / result.requested_units * 100 if result.requested_units else 0.0
    )
    print("\nDemand simulation:")
    print(f"  Branches:               {result.branch_count:,}")
    print(f"  Days:                   {result.simulated_days:,}")
    print(f"  Baskets:                {result.baskets:,}")
    print(f"  Demand lines:           {result.demand_lines:,}")
    print(f"  Requested units:        {result.requested_units:,}")
    print(f"  Fulfilled units:        {result.fulfilled_units:,}")
    print(f"  Lost units:             {result.lost_units:,}")
    print(f"  Unit fulfillment rate:  {fulfillment_rate:.2f}%")
    print(f"  Reorder triggers:       {result.reorder_triggers:,}")
    print(f"  Output partitions:      {result.partition_count:,}")
    print("\nGenerated locations:")
    for name in (
        "demand_lines",
        "batch_allocations",
        "stock_movements",
        "reorder_triggers",
        "ending_inventory",
        "ending_batches",
    ):
        print(f"  {result.output_dir / name}")
    print(f"  {result.daily_kpi_path}")
    print(f"  {result.manifest_path}")
    print(f"  {result.success_marker_path}")
    print("\nSTAGE_2E_STATUS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
