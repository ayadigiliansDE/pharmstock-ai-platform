"""Product master-data contracts for the PharmStock domain.

The domain model deliberately describes medication/product facts only.
Inventory levels, pharmacy-specific prices, demand, and sales do not belong here;
those concepts change independently and will be modeled in later stages.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NonEmptyText = Annotated[str, Field(min_length=1, max_length=500)]


class PrescriptionStatus(StrEnum):
    """How the product is supplied to a patient in a given market."""

    PRESCRIPTION = "prescription"
    OTC = "otc"
    UNKNOWN = "unknown"


class RegulatoryStatus(StrEnum):
    """Current high-level market status from the source registry."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


class ActiveIngredient(BaseModel):
    """One active medicinal ingredient and its source strength text.

    `strength_text` is intentionally textual instead of forcing every source into a
    numeric schema. Real drug registries use forms such as ``500 mg``,
    ``250 mg/5 mL`` or strengths composed from multiple salts.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    name: NonEmptyText
    strength_text: NonEmptyText | None = None


class ProductIdentifiers(BaseModel):
    """Identifiers that allow one product to be reconciled across registries."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    rxnorm_rxcui: str | None = Field(default=None, min_length=1, max_length=32)
    ndc_product_code: str | None = Field(default=None, min_length=1, max_length=32)
    ndc_package_code: str | None = Field(default=None, min_length=1, max_length=32)
    gtin: str | None = Field(default=None, min_length=8, max_length=14)
    local_registration_number: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("gtin")
    @classmethod
    def validate_gtin(cls, value: str | None) -> str | None:
        if value is not None and not value.isdigit():
            raise ValueError("gtin must contain digits only")
        return value

    @model_validator(mode="after")
    def require_at_least_one_identifier(self) -> ProductIdentifiers:
        if not any(
            (
                self.rxnorm_rxcui,
                self.ndc_product_code,
                self.ndc_package_code,
                self.gtin,
                self.local_registration_number,
            )
        ):
            raise ValueError("at least one external product identifier is required")
        return self


class ProductSource(BaseModel):
    """Provenance for a product record imported from an authoritative source."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    system: NonEmptyText
    record_id: NonEmptyText
    source_updated_at: datetime | None = None


class Product(BaseModel):
    """A saleable pharmaceutical product in the platform product master.

    The model can represent branded or generic products, combination products,
    multiple administration routes, and identifiers from several registries.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    product_id: UUID = Field(default_factory=uuid4)
    display_name: NonEmptyText
    brand_name: NonEmptyText | None = None
    generic_name: NonEmptyText | None = None
    dosage_form: NonEmptyText
    routes: tuple[NonEmptyText, ...] = ()
    active_ingredients: tuple[ActiveIngredient, ...] = Field(min_length=1)
    package_description: NonEmptyText | None = None
    manufacturer: NonEmptyText | None = None
    prescription_status: PrescriptionStatus = PrescriptionStatus.UNKNOWN
    regulatory_status: RegulatoryStatus = RegulatoryStatus.UNKNOWN
    market_code: str = Field(min_length=2, max_length=2)
    identifiers: ProductIdentifiers
    source: ProductSource

    @field_validator("market_code")
    @classmethod
    def normalize_market_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized.isalpha():
            raise ValueError("market_code must be a two-letter country code")
        return normalized

    @field_validator("routes")
    @classmethod
    def deduplicate_routes(cls, routes: tuple[str, ...]) -> tuple[str, ...]:
        # Preserve source order while preventing duplicate route labels.
        return tuple(dict.fromkeys(route.casefold() for route in routes))
