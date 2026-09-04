"""Demand and unit-fulfillment contracts for the synthetic Stage 2E simulator.

The current simulator deliberately models *quantities* instead of inventing market
prices. A demand request records what a customer wanted; a demand outcome records
what stock could actually fulfill. Monetary POS facts can be added later when a
trusted market-price source is available.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from pharmstock.domain.batches import FEFOAllocation
from pharmstock.domain.transactions import SaleChannel


class DemandFulfillmentStatus(StrEnum):
    """Result of trying to satisfy one requested product quantity."""

    FULFILLED = "fulfilled"
    PARTIAL = "partial"
    STOCKOUT = "stockout"


class DemandRequest(BaseModel):
    """One product-level demand line inside a synthetic customer basket."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    demand_id: UUID = Field(default_factory=uuid4)
    basket_id: UUID
    branch_id: UUID
    product_id: UUID
    occurred_at: AwareDatetime
    channel: SaleChannel
    requested_quantity: int = Field(gt=0, le=1_000)
    simulation_source: Literal["synthetic_demand_engine"] = "synthetic_demand_engine"

    @field_validator("occurred_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class DemandOutcome(BaseModel):
    """Validated stock-fulfillment result for one demand request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    demand: DemandRequest
    fulfilled_quantity: int = Field(ge=0, le=1_000)
    lost_quantity: int = Field(ge=0, le=1_000)
    status: DemandFulfillmentStatus
    fefo_allocations: tuple[FEFOAllocation, ...] = ()

    @model_validator(mode="after")
    def validate_quantity_math_and_status(self) -> DemandOutcome:
        requested = self.demand.requested_quantity
        if self.fulfilled_quantity + self.lost_quantity != requested:
            raise ValueError("fulfilled_quantity + lost_quantity must equal requested_quantity")

        expected = (
            DemandFulfillmentStatus.FULFILLED
            if self.fulfilled_quantity == requested
            else DemandFulfillmentStatus.STOCKOUT
            if self.fulfilled_quantity == 0
            else DemandFulfillmentStatus.PARTIAL
        )
        if self.status is not expected:
            raise ValueError(f"status must be {expected.value} for the supplied quantities")

        allocated = sum(item.quantity for item in self.fefo_allocations)
        if allocated != self.fulfilled_quantity:
            raise ValueError("FEFO allocation quantity must equal fulfilled_quantity")
        return self
