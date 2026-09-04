from datetime import time

import pytest
from pydantic import ValidationError

from pharmstock.domain import (
    BranchLocation,
    CapacityProfile,
    DailyOperatingHours,
    OperatingProfile,
    OrganizationType,
    PharmacyBranch,
    PharmacyOrganization,
    PharmacyScale,
    PharmacyType,
    ServiceMode,
    Weekday,
)


def build_week() -> tuple[DailyOperatingHours, ...]:
    return tuple(
        DailyOperatingHours(
            weekday=weekday,
            opens_at=time(8, 0),
            closes_at=time(23, 0),
        )
        for weekday in Weekday
    )


def build_organization() -> PharmacyOrganization:
    return PharmacyOrganization(
        organization_code="pharm-001",
        legal_name="Example Pharmacy Group SAE",
        display_name="Example Pharmacy",
        organization_type=OrganizationType.CHAIN,
        market_code="eg",
    )


def build_branch(**overrides: object) -> PharmacyBranch:
    organization = build_organization()
    payload: dict[str, object] = {
        "organization_id": organization.organization_id,
        "branch_code": "cai-nasr-001",
        "display_name": "Example Pharmacy - Nasr City",
        "pharmacy_type": PharmacyType.COMMUNITY,
        "scale": PharmacyScale.MEDIUM,
        "location": BranchLocation(
            governorate="Cairo",
            city="Cairo",
            district="Nasr City",
            latitude=30.0561,
            longitude=31.3300,
        ),
        "operating_profile": OperatingProfile(
            timezone="Africa/Cairo",
            schedule=build_week(),
            service_modes=frozenset(
                {ServiceMode.IN_STORE, ServiceMode.DELIVERY, ServiceMode.CLICK_AND_COLLECT}
            ),
        ),
        "capacity": CapacityProfile(
            assortment_capacity_skus=3_500,
            storage_capacity_units=25_000,
            floor_area_m2=180,
            checkout_points=3,
            cold_chain_supported=True,
            cold_chain_capacity_units=600,
        ),
    }
    payload.update(overrides)
    return PharmacyBranch.model_validate(payload)


def test_organization_codes_and_market_are_normalized() -> None:
    organization = build_organization()

    assert organization.organization_code == "PHARM-001"
    assert organization.market_code == "EG"


def test_branch_code_and_location_country_are_normalized() -> None:
    branch = build_branch()

    assert branch.branch_code == "CAI-NASR-001"
    assert branch.location.country_code == "EG"


def test_location_requires_coordinate_pair() -> None:
    with pytest.raises(ValidationError):
        BranchLocation(
            governorate="Cairo",
            city="Cairo",
            latitude=30.0,
        )


def test_operating_profile_requires_all_seven_unique_days() -> None:
    incomplete_week = build_week()[:-1]

    with pytest.raises(ValidationError):
        OperatingProfile(schedule=incomplete_week)


def test_schedule_is_canonicalized_monday_to_sunday() -> None:
    profile = OperatingProfile(schedule=tuple(reversed(build_week())))

    assert tuple(day.weekday for day in profile.schedule) == tuple(Weekday)


def test_24_hour_day_cannot_also_have_opening_times() -> None:
    with pytest.raises(ValidationError):
        DailyOperatingHours(
            weekday=Weekday.MONDAY,
            is_24_hours=True,
            opens_at=time(0, 0),
            closes_at=time(23, 59),
        )


def test_overnight_hours_are_allowed() -> None:
    day = DailyOperatingHours(
        weekday=Weekday.FRIDAY,
        opens_at=time(18, 0),
        closes_at=time(2, 0),
    )

    assert day.opens_at == time(18, 0)
    assert day.closes_at == time(2, 0)


def test_cold_chain_capacity_requires_cold_chain_support() -> None:
    with pytest.raises(ValidationError):
        CapacityProfile(
            assortment_capacity_skus=1_000,
            storage_capacity_units=5_000,
            cold_chain_supported=False,
            cold_chain_capacity_units=100,
        )


def test_cold_chain_support_requires_positive_capacity() -> None:
    with pytest.raises(ValidationError):
        CapacityProfile(
            assortment_capacity_skus=1_000,
            storage_capacity_units=5_000,
            cold_chain_supported=True,
            cold_chain_capacity_units=0,
        )


def test_storage_capacity_cannot_be_less_than_assortment_capacity() -> None:
    with pytest.raises(ValidationError):
        CapacityProfile(
            assortment_capacity_skus=5_000,
            storage_capacity_units=2_000,
        )


def test_branch_is_immutable_after_validation() -> None:
    branch = build_branch()

    with pytest.raises(ValidationError):
        branch.display_name = "Changed"  # type: ignore[misc]
