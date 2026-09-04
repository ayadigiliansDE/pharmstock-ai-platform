"""Build the Stage 7B production-like Egyptian pharmacy network snapshot."""

from __future__ import annotations

import argparse
from pathlib import Path

from pharmstock.simulation import (
    CAPMAS_GENERAL_PHARMACIES_2024,
    CAPMAS_POPULATION_2024_TOTAL,
    ProductionNetworkProfile,
    ProductionPharmacyNetworkGenerator,
    export_production_network,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the Stage 7B calibrated Egyptian pharmacy network"
    )
    parser.add_argument(
        "--profile",
        choices=[profile.value for profile in ProductionNetworkProfile],
        default=ProductionNetworkProfile.ACCEPTANCE.value,
    )
    parser.add_argument(
        "--branches",
        type=int,
        default=None,
        help="Optional explicit branch count; must still cover all 27 governorates",
    )
    parser.add_argument("--seed", type=int, default=20260823)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/stage7b"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    profile = ProductionNetworkProfile(args.profile)
    generator = ProductionPharmacyNetworkGenerator(seed=args.seed)
    result = generator.generate(profile=profile, branch_count=args.branches)
    paths = export_production_network(result, args.output)
    summary = result.summary()

    print("=== PharmStock V2 / Stage 7B Production Egyptian Pharmacy Network ===")
    print(f"Profile:                    {summary['profile']}")
    print(f"CAPMAS population 2024:     {CAPMAS_POPULATION_2024_TOTAL:,}")
    print(f"CAPMAS general pharmacies:  {CAPMAS_GENERAL_PHARMACIES_2024:,}")
    print(f"Modeled branches:           {summary['branch_count']:,}")
    print(f"Organizations:              {summary['organization_count']:,}")
    print(f"Governorates covered:       {summary['governorate_count']} / 27")
    print(f"Urban modeled branches:     {summary['urban_branch_count']:,}")
    print(f"Rural modeled branches:     {summary['rural_branch_count']:,}")
    print(f"Market coverage sample:     {summary['market_coverage_ratio']:.2%}")
    print(f"Branch expansion weight:    {summary['branch_expansion_weight']:.4f}")
    print("Provenance:                 SYNTHETIC_CALIBRATED")
    print("Real pharmacy identities:   NO")
    print("Cloud mutation:             NO")
    print("\nGenerated files:")
    for key in ("organizations", "branches", "calibration", "summary", "quality"):
        print(f"  {paths[key]}")
    print("\nSTAGE_7B_STATUS=PASS")


if __name__ == "__main__":
    main()
