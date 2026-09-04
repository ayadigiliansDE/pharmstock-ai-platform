"""Procurement and replenishment contracts for PharmStock.

These contracts intentionally exclude prices and costs. Stage 2F models the
physical replenishment cycle only. Stage 2F.1 expands the synthetic supplier
master so procurement can model a broad distributor/wholesaler ecosystem while
keeping the truth boundary explicit: supplier identities and service metrics are
simulator assumptions, not records of real Egyptian distributors.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class SupplierType(StrEnum):
    """Synthetic supplier archetypes used by the procurement simulator."""

    NATIONAL_DISTRIBUTOR = "national_distributor"
    REGIONAL_WHOLESALER = "regional_wholesaler"
    LOCAL_WHOLESALER = "local_wholesaler"
    DIRECT_MANUFACTURER = "direct_manufacturer"
    COLD_CHAIN_SPECIALIST = "cold_chain_specialist"


class SupplierProfile(BaseModel):
    """Stable synthetic supplier master data.

    Defaults preserve the original Stage 2F six-supplier checkpoint. Stage 2F.1
    fills the extended fields with deterministic synthetic service metrics.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    supplier_id: UUID = Field(default_factory=uuid4)
    supplier_code: str = Field(min_length=1, max_length=40)
    display_name: str = Field(min_length=1, max_length=160)
    supplier_type: SupplierType
    market_code: str = Field(default="EG", min_length=2, max_length=2)
    base_lead_time_days: int = Field(ge=1, le=30)
    service_regions: tuple[str, ...] = Field(min_length=1)
    service_governorates: tuple[str, ...] = ()
    catalog_coverage_ratio: float = Field(default=1.0, gt=0.0, le=1.0)
    expected_fill_rate: float = Field(default=1.0, ge=0.5, le=1.0)
    reliability_score: float = Field(default=1.0, ge=0.5, le=1.0)
    cycle_capacity_units: int = Field(default=100_000_000, ge=100)
    cold_chain_supported: bool = False
    synthetic_record: bool = True

    @field_validator("supplier_code", "market_code")
    @classmethod
    def normalize_codes(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("service_regions")
    @classmethod
    def unique_regions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip().lower() for item in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("service_regions must be unique")
        return normalized

    @field_validator("service_governorates")
    @classmethod
    def unique_governorates(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in values)
        if len(set(item.casefold() for item in normalized)) != len(normalized):
            raise ValueError("service_governorates must be unique")
        return normalized


class PurchaseOrderLine(BaseModel):
    """One product quantity requested from a supplier."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: UUID
    ordered_quantity: int = Field(gt=0, le=100_000_000)
    source_reorder_demand_id: UUID | None = None


class PurchaseOrder(BaseModel):
    """A physical replenishment request with no monetary fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    purchase_order_id: UUID = Field(default_factory=uuid4)
    branch_id: UUID
    supplier_id: UUID
    ordered_at: AwareDatetime
    expected_delivery_on: date
    line_items: tuple[PurchaseOrderLine, ...] = Field(min_length=1, max_length=50_000)
    procurement_cycle_id: UUID
    synthetic_supplier_assignment: bool = True

    @field_validator("ordered_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ordered_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_order(self) -> PurchaseOrder:
        if self.expected_delivery_on < self.ordered_at.date():
            raise ValueError("expected_delivery_on cannot be before ordered_at")
        product_ids = [item.product_id for item in self.line_items]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("purchase order line_items must contain unique product_id values")
        return self

    @property
    def total_ordered_quantity(self) -> int:
        return sum(item.ordered_quantity for item in self.line_items)


class GoodsReceiptLine(BaseModel):
    """One received product batch created from a delivered purchase order line."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    product_id: UUID
    received_quantity: int = Field(gt=0, le=100_000_000)
    batch_number: str = Field(min_length=1, max_length=120)
    expires_on: date


class GoodsReceipt(BaseModel):
    """Physical receipt of a procurement purchase order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt_id: UUID = Field(default_factory=uuid4)
    purchase_order_id: UUID
    branch_id: UUID
    supplier_id: UUID
    received_at: AwareDatetime
    line_items: tuple[GoodsReceiptLine, ...] = Field(min_length=1, max_length=50_000)

    @field_validator("received_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("received_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_receipt(self) -> GoodsReceipt:
        product_ids = [item.product_id for item in self.line_items]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("goods receipt line_items must contain unique product_id values")
        received_date = self.received_at.date()
        if any(item.expires_on <= received_date for item in self.line_items):
            raise ValueError("received batches must expire after their receipt date")
        return self

    @property
    def total_received_quantity(self) -> int:
        return sum(item.received_quantity for item in self.line_items)
