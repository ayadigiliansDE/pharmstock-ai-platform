from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from pharmstock.simulation import (
    CAPMAS_GENERAL_PHARMACIES_2024,
    CAPMAS_PHARMACY_DENSITY_PER_1000,
    CAPMAS_POPULATION_2024_TOTAL,
    EGYPT_GOVERNORATES,
    PROFILE_BRANCH_COUNTS,
    ProductionNetworkProfile,
    ProductionPharmacyNetworkGenerator,
    export_production_network,
)


def test_capmas_2024_calibration_constants_are_stable() -> None:
    assert CAPMAS_POPULATION_2024_TOTAL == 105_914_499
    assert CAPMAS_GENERAL_PHARMACIES_2024 == 86_741
    assert CAPMAS_PHARMACY_DENSITY_PER_1000 == pytest.approx(0.8189719143)


def test_all_governorates_have_urban_share_reference() -> None:
    assert len(EGYPT_GOVERNORATES) == 27
    assert all(0.0 <= item.urban_share_2024 <= 1.0 for item in EGYPT_GOVERNORATES)
    assert sum(item.population_2024 for item in EGYPT_GOVERNORATES) == 105_914_499


def test_profile_sizes_include_acceptance_and_full_market() -> None:
    assert PROFILE_BRANCH_COUNTS[ProductionNetworkProfile.DEV] == 27
    assert PROFILE_BRANCH_COUNTS[ProductionNetworkProfile.ACCEPTANCE] == 5_000
    assert (
        PROFILE_BRANCH_COUNTS[ProductionNetworkProfile.FULL_MARKET]
        == CAPMAS_GENERAL_PHARMACIES_2024
    )


def test_acceptance_network_covers_27_governorates() -> None:
    result = ProductionPharmacyNetworkGenerator(seed=7).generate()
    assert result.branch_count == 5_000
    assert len({row.governorate_code for row in result.branches}) == 27
    assert sum(row.modeled_branch_count for row in result.governorate_calibration) == 5_000


def test_full_market_allocation_reconciles_to_capmas_national_total() -> None:
    result = ProductionPharmacyNetworkGenerator(seed=8).generate(
        profile=ProductionNetworkProfile.DEV
    )
    assert sum(
        row.modeled_full_market_pharmacies for row in result.governorate_calibration
    ) == CAPMAS_GENERAL_PHARMACIES_2024


def test_network_is_deterministic_for_same_seed() -> None:
    first = ProductionPharmacyNetworkGenerator(seed=9).generate(
        profile=ProductionNetworkProfile.DEV
    )
    second = ProductionPharmacyNetworkGenerator(seed=9).generate(
        profile=ProductionNetworkProfile.DEV
    )
    assert first.organizations == second.organizations
    assert first.branches == second.branches


def test_branch_identity_and_organization_foreign_keys_are_valid() -> None:
    result = ProductionPharmacyNetworkGenerator(seed=10).generate(
        profile=ProductionNetworkProfile.DEV
    )
    branch_ids = {row.branch_id for row in result.branches}
    branch_codes = {row.branch_code for row in result.branches}
    organization_ids = {row.organization_id for row in result.organizations}
    assert len(branch_ids) == result.branch_count
    assert len(branch_codes) == result.branch_count
    assert {row.organization_id for row in result.branches} <= organization_ids


def test_generated_branch_records_are_explicitly_synthetic_calibrated() -> None:
    result = ProductionPharmacyNetworkGenerator(seed=11).generate(
        profile=ProductionNetworkProfile.DEV
    )
    assert all(row.synthetic_record for row in result.branches)
    assert all(row.provenance_class == "SYNTHETIC_CALIBRATED" for row in result.branches)
    assert all(row.display_name.startswith("Synthetic Pharmacy") for row in result.branches)


def test_branch_expansion_weight_matches_market_sample_ratio() -> None:
    result = ProductionPharmacyNetworkGenerator(seed=12).generate(
        profile=ProductionNetworkProfile.ACCEPTANCE
    )
    assert result.market_coverage_ratio == pytest.approx(5_000 / 86_741)
    assert result.branch_expansion_weight == pytest.approx(86_741 / 5_000)
    assert all(
        row.branch_expansion_weight == pytest.approx(result.branch_expansion_weight)
        for row in result.branches
    )


def test_locality_assignment_contains_urban_and_rural_branches() -> None:
    result = ProductionPharmacyNetworkGenerator(seed=13).generate(
        profile=ProductionNetworkProfile.ACCEPTANCE
    )
    localities = {row.locality_type for row in result.branches}
    assert localities == {"urban", "rural"}


def test_branch_count_below_27_is_rejected() -> None:
    with pytest.raises(ValueError, match="cover all 27 governorates"):
        ProductionPharmacyNetworkGenerator().generate(branch_count=26)


def test_export_contains_quality_and_reference_artifacts(tmp_path: Path) -> None:
    result = ProductionPharmacyNetworkGenerator(seed=14).generate(
        profile=ProductionNetworkProfile.DEV
    )
    paths = export_production_network(result, tmp_path)
    assert paths["success"].read_text(encoding="utf-8").strip() == "STAGE_7B_STATUS=PASS"
    quality = json.loads(paths["quality"].read_text(encoding="utf-8"))
    assert quality["status"] == "PASS"
    assert quality["checks"]["all_27_governorates_present"] is True
    references = json.loads(paths["references"].read_text(encoding="utf-8"))
    assert references["pharmacy_count_reference"]["general_pharmacies"] == 86_741
    with paths["branches"].open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 27
    assert {row["provenance_class"] for row in rows} == {"SYNTHETIC_CALIBRATED"}
