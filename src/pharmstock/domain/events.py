"""Versioned domain-event envelopes prepared for a future Kafka boundary.

These contracts intentionally know nothing about Kafka.  Stage 3 will serialize and
publish them after business processing succeeds.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from pharmstock.domain.inventory import InventoryItem, StockMovement
from pharmstock.domain.transactions import RestockReceipt, Sale


class EventPayload(BaseModel):
    """Base payload policy shared by all V1 domain events."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DomainEvent[PayloadT: BaseModel](BaseModel):
    """Common immutable event envelope.

    `schema_version` versions the public event contract independently of the Python
    package version. Consumers can therefore evolve safely when Kafka is introduced.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    event_id: UUID = Field(default_factory=uuid4)
    event_type: str = Field(min_length=3, max_length=120)
    schema_version: str = Field(pattern=r"^[1-9]\d*\.\d+$")
    aggregate_type: str = Field(min_length=1, max_length=80)
    aggregate_id: UUID
    occurred_at: AwareDatetime
    recorded_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    correlation_id: UUID
    causation_id: UUID | None = None
    payload: PayloadT

    @field_validator("occurred_at", "recorded_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class SaleRecordedPayload(EventPayload):
    sale: Sale


class SaleRecordedEvent(DomainEvent[SaleRecordedPayload]):
    event_type: Literal["sale.recorded"] = "sale.recorded"
    schema_version: Literal["1.0"] = "1.0"
    aggregate_type: Literal["sale"] = "sale"

    @classmethod
    def from_sale(cls, sale: Sale, *, correlation_id: UUID | None = None) -> SaleRecordedEvent:
        return cls(
            aggregate_id=sale.sale_id,
            occurred_at=sale.occurred_at,
            correlation_id=correlation_id or sale.sale_id,
            payload=SaleRecordedPayload(sale=sale),
        )


class RestockReceivedPayload(EventPayload):
    restock: RestockReceipt


class RestockReceivedEvent(DomainEvent[RestockReceivedPayload]):
    event_type: Literal["restock.received"] = "restock.received"
    schema_version: Literal["1.0"] = "1.0"
    aggregate_type: Literal["restock"] = "restock"

    @classmethod
    def from_restock(
        cls,
        restock: RestockReceipt,
        *,
        correlation_id: UUID | None = None,
    ) -> RestockReceivedEvent:
        return cls(
            aggregate_id=restock.restock_id,
            occurred_at=restock.received_at,
            correlation_id=correlation_id or restock.restock_id,
            payload=RestockReceivedPayload(restock=restock),
        )


class StockChangedPayload(EventPayload):
    movement: StockMovement


class StockChangedEvent(DomainEvent[StockChangedPayload]):
    event_type: Literal["inventory.stock_changed"] = "inventory.stock_changed"
    schema_version: Literal["1.0"] = "1.0"
    aggregate_type: Literal["inventory_item"] = "inventory_item"

    @classmethod
    def from_movement(
        cls,
        movement: StockMovement,
        *,
        inventory_item_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
    ) -> StockChangedEvent:
        return cls(
            aggregate_id=inventory_item_id,
            occurred_at=movement.occurred_at,
            correlation_id=correlation_id,
            causation_id=causation_id,
            payload=StockChangedPayload(movement=movement),
        )


class ReorderRequiredPayload(EventPayload):
    branch_id: UUID
    product_id: UUID
    available_quantity: int = Field(ge=0)
    reorder_point: int = Field(ge=0)
    target_stock_level: int = Field(gt=0)
    recommended_reorder_quantity: int = Field(gt=0)
    inventory_version: int = Field(ge=1)


class ReorderRequiredEvent(DomainEvent[ReorderRequiredPayload]):
    event_type: Literal["inventory.reorder_required"] = "inventory.reorder_required"
    schema_version: Literal["1.0"] = "1.0"
    aggregate_type: Literal["inventory_item"] = "inventory_item"

    @classmethod
    def from_inventory(
        cls,
        inventory: InventoryItem,
        *,
        occurred_at: datetime,
        correlation_id: UUID,
        causation_id: UUID | None = None,
    ) -> ReorderRequiredEvent:
        if not inventory.reorder_required or inventory.recommended_reorder_quantity <= 0:
            raise ValueError("inventory item is not currently reorder-required")

        return cls(
            aggregate_id=inventory.inventory_item_id,
            occurred_at=occurred_at,
            correlation_id=correlation_id,
            causation_id=causation_id,
            payload=ReorderRequiredPayload(
                branch_id=inventory.branch_id,
                product_id=inventory.product_id,
                available_quantity=inventory.available_quantity,
                reorder_point=inventory.reorder_policy.reorder_point,
                target_stock_level=inventory.reorder_policy.target_stock_level,
                recommended_reorder_quantity=inventory.recommended_reorder_quantity,
                inventory_version=inventory.version,
            ),
        )

class UnitSaleFulfilledPayload(EventPayload):
    """Physical unit-sale fact emitted by the simulator without monetary values."""

    demand_id: UUID
    basket_id: UUID
    branch_id: UUID
    product_id: UUID
    channel: str = Field(min_length=1, max_length=40)
    requested_quantity: int = Field(gt=0)
    fulfilled_quantity: int = Field(gt=0)
    lost_quantity: int = Field(ge=0)
    fulfillment_status: Literal["fulfilled", "partial"]
    pricing_status: Literal["not_simulated"] = "not_simulated"

    @model_validator(mode="after")
    def validate_quantity_accounting(self) -> UnitSaleFulfilledPayload:
        if self.fulfilled_quantity + self.lost_quantity != self.requested_quantity:
            raise ValueError("fulfilled_quantity + lost_quantity must equal requested_quantity")
        if self.fulfilled_quantity > self.requested_quantity:
            raise ValueError("fulfilled_quantity cannot exceed requested_quantity")
        return self


class UnitSaleFulfilledEvent(DomainEvent[UnitSaleFulfilledPayload]):
    event_type: Literal["sale.units_fulfilled"] = "sale.units_fulfilled"
    schema_version: Literal["1.0"] = "1.0"
    aggregate_type: Literal["demand_line"] = "demand_line"


class InventoryQuantityChangedPayload(EventPayload):
    movement_id: UUID
    branch_id: UUID
    product_id: UUID
    movement_type: Literal["sale", "restock"]
    quantity_delta: int
    on_hand_before: int = Field(ge=0)
    on_hand_after: int = Field(ge=0)
    inventory_version_after: int = Field(ge=2)
    reference_id: UUID

    @field_validator("quantity_delta")
    @classmethod
    def quantity_delta_cannot_be_zero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("quantity_delta cannot be zero")
        return value

    @model_validator(mode="after")
    def validate_transition_math(self) -> InventoryQuantityChangedPayload:
        if self.on_hand_before + self.quantity_delta != self.on_hand_after:
            raise ValueError("quantity_delta does not match on-hand transition")
        if self.movement_type == "sale" and self.quantity_delta >= 0:
            raise ValueError("sale quantity_delta must be negative")
        if self.movement_type == "restock" and self.quantity_delta <= 0:
            raise ValueError("restock quantity_delta must be positive")
        return self


class InventoryQuantityChangedEvent(DomainEvent[InventoryQuantityChangedPayload]):
    event_type: Literal["inventory.quantity_changed"] = "inventory.quantity_changed"
    schema_version: Literal["1.0"] = "1.0"
    aggregate_type: Literal["inventory_item"] = "inventory_item"


class PurchaseOrderCreatedPayload(EventPayload):
    purchase_order_id: UUID
    procurement_cycle_id: UUID
    branch_id: UUID
    supplier_id: UUID
    expected_delivery_on: date
    line_count: int = Field(gt=0)
    ordered_units: int = Field(gt=0)
    monetary_values_generated: Literal[False] = False


class PurchaseOrderCreatedEvent(DomainEvent[PurchaseOrderCreatedPayload]):
    event_type: Literal["purchase_order.created"] = "purchase_order.created"
    schema_version: Literal["1.0"] = "1.0"
    aggregate_type: Literal["purchase_order"] = "purchase_order"


class GoodsReceiptReceivedPayload(EventPayload):
    receipt_id: UUID
    purchase_order_id: UUID
    branch_id: UUID
    supplier_id: UUID
    line_count: int = Field(gt=0)
    received_units: int = Field(gt=0)


class GoodsReceiptReceivedEvent(DomainEvent[GoodsReceiptReceivedPayload]):
    event_type: Literal["goods_receipt.received"] = "goods_receipt.received"
    schema_version: Literal["1.0"] = "1.0"
    aggregate_type: Literal["goods_receipt"] = "goods_receipt"


class RestockAppliedPayload(EventPayload):
    movement_id: UUID
    receipt_id: UUID
    purchase_order_id: UUID
    branch_id: UUID
    product_id: UUID
    quantity: int = Field(gt=0)
    on_hand_before: int = Field(ge=0)
    on_hand_after: int = Field(ge=0)
    inventory_version_after: int = Field(ge=2)

    @model_validator(mode="after")
    def validate_restock_math(self) -> RestockAppliedPayload:
        if self.on_hand_before + self.quantity != self.on_hand_after:
            raise ValueError("restock quantity does not match on-hand transition")
        return self


class RestockAppliedEvent(DomainEvent[RestockAppliedPayload]):
    event_type: Literal["restock.applied"] = "restock.applied"
    schema_version: Literal["1.0"] = "1.0"
    aggregate_type: Literal["inventory_item"] = "inventory_item"
