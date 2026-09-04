"""Build and validate the Stage 5D local master-data snapshot."""

from __future__ import annotations

from pathlib import Path

from pharmstock.masterdata.stage5d import prepare_master_snapshot


def main() -> None:
    report = prepare_master_snapshot(Path("artifacts/stage5d"))
    counts = report["table_counts"]
    print("=== PharmStock V2 / Stage 5D Master Data Local Snapshot ===")
    print(f"Products:              {counts['product_master']:,}")
    print(f"Organizations:         {counts['pharmacy_organization_master']:,}")
    print(f"Branches:              {counts['pharmacy_branch_master']:,}")
    print(f"Suppliers:             {counts['supplier_master']:,}")
    print(f"Total master rows:     {report['total_master_rows']:,}")
    print("Product source:        official openFDA NDC / US")
    print("Branch network:        SYNTHETIC / EG")
    print("Supplier network:      SYNTHETIC")
    print("Monetary data added:   NO")
    print("Cloud mutation:        NO")
    print("\nGenerated files:")
    print(f"  {Path('artifacts/stage5d/master_ready').resolve()}")
    print(f"  {Path('artifacts/stage5d/contracts').resolve()}")
    print(f"  {Path('artifacts/stage5d/master_snapshot_manifest.json').resolve()}")
    print("\nSTAGE_5D_STATUS=PASS")


if __name__ == "__main__":
    main()
