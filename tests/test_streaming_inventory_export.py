import csv
import json
from datetime import date
from pathlib import Path
from uuid import UUID

from pharmstock.domain import (
    ActiveIngredient,
    PrescriptionStatus,
    Product,
    ProductIdentifiers,
    ProductSource,
    RegulatoryStatus,
)
from pharmstock.simulation import (
    InitialInventoryGenerator,
    PharmacyNetworkGenerator,
    export_initial_inventory_streaming,
)


def build_products(count: int = 160) -> list[Product]:
    return [
        Product(
            product_id=UUID(int=index + 1),
            display_name=f"Medicine {index:04d}",
            generic_name=f"Ingredient {index:04d}",
            dosage_form="TABLET" if index % 3 else "INJECTION",
            active_ingredients=(
                ActiveIngredient(name=f"Ingredient {index:04d}", strength_text="10 mg"),
            ),
            prescription_status=PrescriptionStatus.PRESCRIPTION,
            regulatory_status=RegulatoryStatus.ACTIVE,
            market_code="US",
            identifiers=ProductIdentifiers(ndc_package_code=f"00001-{index:04d}-01"),
            source=ProductSource(system="test", record_id=str(index)),
        )
        for index in range(count)
    ]


def csv_data_rows(path: Path) -> int:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return max(sum(1 for _ in csv.reader(handle)) - 1, 0)


def test_streaming_export_partitions_branches_and_writes_manifest(tmp_path: Path) -> None:
    network = PharmacyNetworkGenerator(seed=7).generate(11)
    result = export_initial_inventory_streaming(
        output_dir=tmp_path,
        generator=InitialInventoryGenerator(seed=7, reference_date=date(2026, 8, 22)),
        network=network,
        products=build_products(),
        branches_per_partition=4,
    )
    assert result.branch_count == 11
    assert result.partition_count == 3
    assert len(list((tmp_path / "inventory").glob("part-*.csv"))) == 3
    assert len(list((tmp_path / "batches").glob("part-*.csv"))) == 3
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["export_mode"] == "bounded_memory_partitioned_csv"
    assert "one branch inventory retained at a time" in manifest["memory_contract"]
    assert result.success_marker_path.exists()
    assert manifest["completion_marker"] == "_SUCCESS"


def test_partition_row_counts_match_manifest_totals(tmp_path: Path) -> None:
    network = PharmacyNetworkGenerator(seed=9).generate(9)
    result = export_initial_inventory_streaming(
        output_dir=tmp_path,
        generator=InitialInventoryGenerator(seed=9, reference_date=date(2026, 8, 22)),
        network=network,
        products=build_products(),
        branches_per_partition=3,
    )
    inventory_rows = sum(
        csv_data_rows(path) for path in (tmp_path / "inventory").glob("part-*.csv")
    )
    batch_rows = sum(csv_data_rows(path) for path in (tmp_path / "batches").glob("part-*.csv"))
    assert inventory_rows == result.inventory_rows
    assert batch_rows == result.batch_rows


def test_streaming_and_in_memory_generation_have_same_totals(tmp_path: Path) -> None:
    network = PharmacyNetworkGenerator(seed=13).generate(7)
    products = build_products()
    in_memory = InitialInventoryGenerator(seed=13, reference_date=date(2026, 8, 22)).generate(
        network=network, products=products
    )
    streamed = export_initial_inventory_streaming(
        output_dir=tmp_path,
        generator=InitialInventoryGenerator(seed=13, reference_date=date(2026, 8, 22)),
        network=network,
        products=products,
        branches_per_partition=2,
    )
    assert streamed.inventory_rows == len(in_memory.inventory_rows)
    assert streamed.batch_rows == len(in_memory.batch_rows)
    assert streamed.total_initial_stock_units == sum(
        row.on_hand_quantity for row in in_memory.inventory_rows
    )


def test_rerun_removes_stale_partition_files(tmp_path: Path) -> None:
    stale_inventory = tmp_path / "inventory" / "part-99999.csv"
    stale_batches = tmp_path / "batches" / "part-99999.csv"
    stale_inventory.parent.mkdir(parents=True)
    stale_batches.parent.mkdir(parents=True)
    stale_inventory.write_text("stale", encoding="utf-8")
    stale_batches.write_text("stale", encoding="utf-8")

    network = PharmacyNetworkGenerator(seed=3).generate(3)
    export_initial_inventory_streaming(
        output_dir=tmp_path,
        generator=InitialInventoryGenerator(seed=3, reference_date=date(2026, 8, 22)),
        network=network,
        products=build_products(),
        branches_per_partition=2,
    )
    assert not stale_inventory.exists()
    assert not stale_batches.exists()


def test_branch_summary_has_exactly_one_row_per_branch(tmp_path: Path) -> None:
    network = PharmacyNetworkGenerator(seed=5).generate(6)
    result = export_initial_inventory_streaming(
        output_dir=tmp_path,
        generator=InitialInventoryGenerator(seed=5, reference_date=date(2026, 8, 22)),
        network=network,
        products=build_products(),
        branches_per_partition=2,
    )
    assert csv_data_rows(result.branch_summary_path) == 6
