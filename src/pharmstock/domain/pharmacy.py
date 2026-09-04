"""Pharmacy master-data contracts for PharmStock AI Platform.

This module models stable business facts about pharmacy organizations and branches.
Transactional facts such as stock on hand, prices, sales, demand and replenishment
belong to later domain modules because they change independently over time.
"""

from __future__ import annotations

from datetime import date, time
from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ShortText = Annotated[str, Field(min_length=1, max_length=120)]
LongText = Annotated[str, Field(min_length=1, max_length=500)]


class OrganizationType(StrEnum):
    """High-level ownership/operator model for a pharmacy business."""

    INDEPENDENT = "independent"
    CHAIN = "chain"
    HOSPITAL_NETWORK = "hospital_network"
    DIGITAL_OPERATOR = "digital_operator"


class PharmacyType(StrEnum):
    """Operational type of an individual pharmacy facility."""

    COMMUNITY = "community"
    HOSPITAL = "hospital"
    CLINIC = "clinic"
    FULFILLMENT_CENTER = "fulfillment_center"


class PharmacyScale(StrEnum):
    """Coarse branch-size segment used by later simulation policies."""

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    FLAGSHIP = "flagship"


class BranchStatus(StrEnum):
    """Whether a branch should participate in operational processing."""

    ACTIVE = "active"
    TEMPORARILY_CLOSED = "temporarily_closed"
    INACTIVE = "inactive"


class Weekday(StrEnum):
    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


class ServiceMode(StrEnum):
    """Ways a branch can serve demand."""

    IN_STORE = "in_store"
    DELIVERY = "delivery"
    CLICK_AND_COLLECT = "click_and_collect"
    ONLINE_FULFILLMENT = "online_fulfillment"


class BranchLocation(BaseModel):
    """Geographic master data for a pharmacy branch.

    Coordinates are optional because imported or synthetic source records may start
    with administrative geography only. If coordinates are supplied, latitude and
    longitude must be supplied together.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    country_code: str = Field(default="EG", min_length=2, max_length=2)
    governorate: ShortText
    city: ShortText
    district: ShortText | None = None
    address_line: LongText | None = None
    postal_code: str | None = Field(default=None, min_length=1, max_length=20)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("country_code")
    @classmethod
    def normalize_country_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized.isalpha():
            raise ValueError("country_code must be a two-letter country code")
        return normalized

    @model_validator(mode="after")
    def coordinates_must_be_paired(self) -> BranchLocation:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self


class DailyOperatingHours(BaseModel):
    """Opening rule for one weekday.

    Overnight schedules are valid: for example, 18:00 -> 02:00 means the branch
    closes after midnight. A true 24-hour day is represented explicitly rather than
    using equal opening and closing times.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    weekday: Weekday
    is_closed: bool = False
    is_24_hours: bool = False
    opens_at: time | None = None
    closes_at: time | None = None

    @model_validator(mode="after")
    def validate_hours(self) -> DailyOperatingHours:
        if self.is_closed and self.is_24_hours:
            raise ValueError("a day cannot be both closed and 24 hours")

        if self.is_closed or self.is_24_hours:
            if self.opens_at is not None or self.closes_at is not None:
                raise ValueError("closed/24-hour days must not define opening times")
            return self

        if self.opens_at is None or self.closes_at is None:
            raise ValueError("normal operating days require opens_at and closes_at")
        if self.opens_at == self.closes_at:
            raise ValueError("equal opening and closing times must use is_24_hours=True")
        return self


class OperatingProfile(BaseModel):
    """Stable weekly operating profile for a pharmacy branch."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    timezone: str = Field(default="Africa/Cairo", min_length=1, max_length=100)
    schedule: tuple[DailyOperatingHours, ...] = Field(min_length=7, max_length=7)
    service_modes: frozenset[ServiceMode] = Field(
        default_factory=lambda: frozenset({ServiceMode.IN_STORE}),
        min_length=1,
    )
    emergency_service: bool = False

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value

    @field_validator("schedule")
    @classmethod
    def require_full_unique_week(
        cls, schedule: tuple[DailyOperatingHours, ...]
    ) -> tuple[DailyOperatingHours, ...]:
        weekdays = [entry.weekday for entry in schedule]
        if len(set(weekdays)) != 7 or set(weekdays) != set(Weekday):
            raise ValueError("schedule must contain every weekday exactly once")

        weekday_order = {weekday: index for index, weekday in enumerate(Weekday)}
        return tuple(sorted(schedule, key=lambda entry: weekday_order[entry.weekday]))


class CapacityProfile(BaseModel):
    """Physical/assortment capacity used to constrain later inventory simulation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    assortment_capacity_skus: int = Field(ge=50, le=100_000)
    storage_capacity_units: int = Field(ge=100, le=100_000_000)
    floor_area_m2: float | None = Field(default=None, gt=0, le=20_000)
    checkout_points: int = Field(default=1, ge=1, le=500)
    cold_chain_supported: bool = False
    cold_chain_capacity_units: int = Field(default=0, ge=0, le=10_000_000)

    @model_validator(mode="after")
    def validate_capacity_relationships(self) -> CapacityProfile:
        if self.storage_capacity_units < self.assortment_capacity_skus:
            raise ValueError(
                "storage_capacity_units cannot be smaller than assortment_capacity_skus"
            )

        if self.cold_chain_supported and self.cold_chain_capacity_units <= 0:
            raise ValueError(
                "cold_chain_capacity_units must be positive when cold chain is supported"
            )

        if not self.cold_chain_supported and self.cold_chain_capacity_units != 0:
            raise ValueError(
                "cold_chain_capacity_units must be zero when cold chain is not supported"
            )
        return self


class PharmacyOrganization(BaseModel):
    """Business entity that owns or operates one or more pharmacy branches."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    organization_id: UUID = Field(default_factory=uuid4)
    organization_code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Z0-9][A-Z0-9_-]*$")
    legal_name: ShortText
    display_name: ShortText
    organization_type: OrganizationType
    market_code: str = Field(default="EG", min_length=2, max_length=2)

    @field_validator("organization_code", mode="before")
    @classmethod
    def normalize_organization_code(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("market_code")
    @classmethod
    def normalize_market_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized.isalpha():
            raise ValueError("market_code must be a two-letter country code")
        return normalized


class PharmacyBranch(BaseModel):
    """One operating pharmacy branch/facility in the platform master data."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    branch_id: UUID = Field(default_factory=uuid4)
    organization_id: UUID
    branch_code: str = Field(min_length=2, max_length=50, pattern=r"^[A-Z0-9][A-Z0-9_-]*$")
    display_name: ShortText
    pharmacy_type: PharmacyType
    scale: PharmacyScale
    location: BranchLocation
    operating_profile: OperatingProfile
    capacity: CapacityProfile
    status: BranchStatus = BranchStatus.ACTIVE
    opened_on: date | None = None

    @field_validator("branch_code", mode="before")
    @classmethod
    def normalize_branch_code(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value
