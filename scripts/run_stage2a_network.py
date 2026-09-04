"""Generate and export the Stage 2A synthetic pharmacy network."""

from __future__ import annotations

import argparse
from pathlib import Path

from pharmstock.simulation import (
    PharmacyNetworkGenerator,
    export_network,
    validate_governorate_reference,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the PharmStock Stage 2A pharmacy network"
    )
    parser.add_argument("--pharmacies", type=int, default=25, help="Number of branches to generate")
    parser.add_argument("--seed", type=int, default=20260822, help="Deterministic random seed")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/stage2a"),
        help="Directory for CSV/JSON output",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    validate_governorate_reference()
    network = PharmacyNetworkGenerator(seed=args.seed).generate(args.pharmacies)
    org_path, branch_path, summary_path = export_network(network, args.output)
    summary = network.summary()

    print("=== PharmStock V2 / Stage 2A ===")
    print(f"Seed:             {summary['seed']}")
    print(f"Organizations:    {summary['organization_count']:,}")
    print(f"Pharmacy branches:{summary['branch_count']:,}")
    print(f"Governorates used:{summary['governorate_count']:,} / 27")
    print("\nBranches by scale:")
    for scale, count in summary["branches_by_scale"].items():
        print(f"  {scale:10s} {count:>7,}")
    print("\nGenerated files:")
    print(f"  {org_path.resolve()}")
    print(f"  {branch_path.resolve()}")
    print(f"  {summary_path.resolve()}")
    print("\nSTAGE_2A_STATUS=PASS")


if __name__ == "__main__":
    main()
