import csv
import json
from datetime import date, datetime, time
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from pharmstock.domain import (
    ActiveIngredient,
    BranchLocation,
    CapacityProfile,
    DailyOperatingHours,
    OperatingProfile,
    PharmacyBranch,
    PharmacyScale,
    PharmacyType,
    PrescriptionStatus,
    Product,
    ProductIdentifiers,
    ProductSource,
    RegulatoryStatus,
    ServiceMode,
    Weekday,
)
from pharmstock.simulation import (
    DemandSimulationPolicy,
    InitialInventoryGenerator,
    PharmacyNetworkGenerator,
    branch_is_open,
    export_demand_simulation,
    export_initial_inventory_streaming,
)


def products(count: int = 90) -> list[Product]:
    return [
        Product(
            product_id=UUID(int=index + 1),
            display_name=f"Medicine {index:04d}",
            generic_name=f"Ingredient {index:04d}",
            dosage_form="TABLET",
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


def build_stage2d(path: Path, *, branches: int = 3, seed: int = 7) -> Path:
    network = PharmacyNetworkGenerator(seed=seed).generate(branches)
    export_initial_inventory_streaming(
        output_dir=path,
        generator=InitialInventoryGenerator(seed=seed, reference_date=date(2026, 8, 22)),
        network=network,
        products=products(),
        branches_per_partition=2,
    )
    return path


def csv_int_sum(directory: Path, field: str) -> int:
    total = 0
    for path in sorted(directory.glob("part-*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            total += sum(int(row[field]) for row in csv.DictReader(handle))
    return total


def rows(directory: Path):
    for path in sorted(directory.glob("part-*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            yield from csv.DictReader(handle)


def test_branch_open_logic_handles_normal_and_overnight_hours() -> None:
    week = []
    for weekday in Weekday:
        if weekday is Weekday.FRIDAY:
            week.append(
                DailyOperatingHours(
                    weekday=weekday,
                    opens_at=time(18, 0),
                    closes_at=time(2, 0),
                )
            )
        else:
            week.append(
                DailyOperatingHours(
                    weekday=weekday,
                    opens_at=time(9, 0),
                    closes_at=time(23, 0),
                )
            )
    branch = PharmacyBranch(
        organization_id=UUID(int=1),
        branch_code="TEST-001",
        display_name="Test Branch",
        pharmacy_type=PharmacyType.COMMUNITY,
        scale=PharmacyScale.MEDIUM,
        location=BranchLocation(governorate="Cairo", city="Cairo"),
        operating_profile=OperatingProfile(
            timezone="Africa/Cairo",
            schedule=tuple(week),
            service_modes=frozenset({ServiceMode.IN_STORE}),
        ),
        capacity=CapacityProfile(
            assortment_capacity_skus=100,
            storage_capacity_units=1000,
        ),
    )
    cairo = ZoneInfo("Africa/Cairo")
    assert branch_is_open(branch, datetime(2026, 8, 21, 23, 0, tzinfo=cairo))
    assert branch_is_open(branch, datetime(2026, 8, 22, 1, 0, tzinfo=cairo))
    assert not branch_is_open(branch, datetime(2026, 8, 22, 3, 0, tzinfo=cairo))


def test_stage2e_writes_success_manifest_and_partitioned_outputs(tmp_path: Path) -> None:
    source = build_stage2d(tmp_path / "stage2d")
    result = export_demand_simulation(
        stage2d_dir=source,
        output_dir=tmp_path / "stage2e",
        start_date=date(2026, 8, 22),
        days=2,
        seed=11,
    )
    assert result.success_marker_path.exists()
    assert result.demand_lines > 0
    assert len(list((result.output_dir / "demand_lines").glob("part-*.csv"))) == 2
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["stage"] == "2E"
    assert manifest["monetary_values_generated"] is False
    assert manifest["pricing_status"] == "not_simulated"
    assert "one branch inventory" in manifest["memory_contract"]


def test_fulfilled_units_reconcile_initial_and_ending_inventory(tmp_path: Path) -> None:
    source = build_stage2d(tmp_path / "stage2d", branches=2, seed=13)
    initial_units = csv_int_sum(source / "inventory", "on_hand_quantity")
    result = export_demand_simulation(
        stage2d_dir=source,
        output_dir=tmp_path / "stage2e",
        start_date=date(2026, 8, 22),
        days=3,
        seed=99,
    )
    ending_units = csv_int_sum(result.output_dir / "ending_inventory", "on_hand_quantity")
    assert initial_units - result.fulfilled_units == ending_units


def test_fefo_allocations_sum_to_fulfilled_units(tmp_path: Path) -> None:
    source = build_stage2d(tmp_path / "stage2d", branches=2, seed=17)
    result = export_demand_simulation(
        stage2d_dir=source,
        output_dir=tmp_path / "stage2e",
        start_date=date(2026, 8, 22),
        days=2,
        seed=5,
    )
    allocated = csv_int_sum(result.output_dir / "batch_allocations", "allocated_quantity")
    assert allocated == result.fulfilled_units


def test_demand_rows_never_claim_prices_or_revenue(tmp_path: Path) -> None:
    source = build_stage2d(tmp_path / "stage2d", branches=1, seed=19)
    result = export_demand_simulation(
        stage2d_dir=source,
        output_dir=tmp_path / "stage2e",
        start_date=date(2026, 8, 22),
        days=1,
        seed=3,
    )
    demand_rows = list(rows(result.output_dir / "demand_lines"))
    assert demand_rows
    assert {row["pricing_status"] for row in demand_rows} == {"not_simulated"}
    assert all("price" not in row and "revenue" not in row for row in demand_rows)


def test_same_seed_produces_same_demand_totals(tmp_path: Path) -> None:
    source = build_stage2d(tmp_path / "stage2d", branches=2, seed=23)
    first = export_demand_simulation(
        stage2d_dir=source,
        output_dir=tmp_path / "run-a",
        start_date=date(2026, 8, 22),
        days=2,
        seed=123,
    )
    second = export_demand_simulation(
        stage2d_dir=source,
        output_dir=tmp_path / "run-b",
        start_date=date(2026, 8, 22),
        days=2,
        seed=123,
    )
    assert (
        first.baskets,
        first.demand_lines,
        first.requested_units,
        first.fulfilled_units,
        first.lost_units,
    ) == (
        second.baskets,
        second.demand_lines,
        second.requested_units,
        second.fulfilled_units,
        second.lost_units,
    )


def test_high_demand_can_create_lost_units_and_stockouts(tmp_path: Path) -> None:
    source = build_stage2d(tmp_path / "stage2d", branches=1, seed=29)
    policy = DemandSimulationPolicy(
        small_daily_baskets=2500,
        medium_daily_baskets=2500,
        large_daily_baskets=2500,
        flagship_daily_baskets=2500,
    )
    result = export_demand_simulation(
        stage2d_dir=source,
        output_dir=tmp_path / "stage2e",
        start_date=date(2026, 8, 22),
        days=2,
        seed=31,
        policy=policy,
    )
    assert result.lost_units > 0
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["stockout_lines"] > 0


def test_incomplete_stage2d_dataset_is_rejected(tmp_path: Path) -> None:
    source = build_stage2d(tmp_path / "stage2d")
    (source / "_SUCCESS").unlink()
    with pytest.raises(ValueError, match="_SUCCESS"):
        export_demand_simulation(
            stage2d_dir=source,
            output_dir=tmp_path / "stage2e",
            start_date=date(2026, 8, 22),
            days=1,
        )
