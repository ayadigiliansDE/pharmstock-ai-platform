"""Inventory state and stock-movement contracts for PharmStock.

Inventory is operational state, not product/pharmacy master data.  The models in
this module are immutable snapshots: stock-changing methods return a new snapshot
plus an immutable movement record instead of mutating an object in place.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, computed_field, model_validator


class InventoryError(ValueError):
    """Base class for inventory business-rule failures."""


class InsufficientStockError(InventoryError):
    """Raised when a sale would consume stock that is not available."""


class InventoryReferenceMismatchError(InventoryError):
    """Raised when a transaction targets a different branch/product item."""


class ReorderPolicy(BaseModel):
    """Branch-product replenishment thresholds.

    `reorder_point` is the available-stock threshold at which replenishment is
    required. `target_stock_level` is the desired available stock after a future
    replenishment cycle.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    reorder_point: int = Field(ge=0, le=100_000_000)
    target_stock_level: int = Field(gt=0, le=100_000_000)

    @model_validator(mode="after")
    def target_must_exceed_reorder_point(self) -> ReorderPolicy:
        if self.target_stock_level <= self.reorder_point:
            raise ValueError("target_stock_level must be greater than reorder_point")
        return self


class StockMovementType(StrEnum):
    """Canonical reasons for a change to physical on-hand stock."""

    SALE = "sale"
    RESTOCK = "restock"
    CUSTOMER_RETURN = "customer_return"
    SUPPLIER_RETURN = "supplier_return"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    DAMAGE = "damage"
    EXPIRY = "expiry"
    ADJUSTMENT = "adjustment"


class StockMovement(BaseModel):
    """Immutable audit record for one inventory quantity transition."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    movement_id: UUID = Field(default_factory=uuid4)
    branch_id: UUID
    product_id: UUID
    movement_type: StockMovementType
    quantity_delta: int
    on_hand_before: int = Field(ge=0)
    on_hand_after: int = Field(ge=0)
    reserved_before: int = Field(ge=0)
    reserved_after: int = Field(ge=0)
    inventory_version_after: int = Field(ge=2)
    reference_type: str = Field(min_length=1, max_length=40)
    reference_id: UUID
    occurred_at: AwareDatetime

    @model_validator(mode="after")
    def validate_transition_math(self) -> StockMovement:
        if self.quantity_delta == 0:
            raise ValueError("quantity_delta cannot be zero")
        if self.on_hand_before + self.quantity_delta != self.on_hand_after:
            raise ValueError("quantity_delta does not match on-hand transition")
        if self.reserved_before > self.on_hand_before:
            raise ValueError("reserved_before cannot exceed on_hand_before")
        if self.reserved_after > self.on_hand_after:
            raise ValueError("reserved_after cannot exceed on_hand_after")
        return self


class InventoryItem(BaseModel):
    """Current stock snapshot for one product at one pharmacy branch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    inventory_item_id: UUID = Field(default_factory=uuid4)
    branch_id: UUID
    product_id: UUID
    on_hand_quantity: int = Field(default=0, ge=0, le=100_000_000)
    reserved_quantity: int = Field(default=0, ge=0, le=100_000_000)
    reorder_policy: ReorderPolicy
    version: int = Field(default=1, ge=1)
    updated_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def reserved_cannot_exceed_on_hand(self) -> InventoryItem:
        if self.reserved_quantity > self.on_hand_quantity:
            raise ValueError("reserved_quantity cannot exceed on_hand_quantity")
        return self

    @computed_field
    @property
    def available_quantity(self) -> int:
        """Stock available for a new sale after existing reservations."""

        return self.on_hand_quantity - self.reserved_quantity

    @computed_field
    @property
    def reorder_required(self) -> bool:
        """Whether current available stock is at/below the reorder threshold."""

        return self.available_quantity <= self.reorder_policy.reorder_point

    @computed_field
    @property
    def recommended_reorder_quantity(self) -> int:
        """Units required to restore available stock to the target level."""

        return max(self.reorder_policy.target_stock_level - self.available_quantity, 0)

    def _check_reference(self, *, branch_id: UUID, product_id: UUID) -> None:
        if branch_id != self.branch_id or product_id != self.product_id:
            raise InventoryReferenceMismatchError(
                "inventory operation branch_id/product_id does not match InventoryItem"
            )

    def _next_snapshot(self, *, on_hand_quantity: int, occurred_at: datetime) -> Self:
        payload = self.model_dump(
            exclude={
                "available_quantity",
                "reorder_required",
                "recommended_reorder_quantity",
            }
        )
        payload.update(
            {
                "on_hand_quantity": on_hand_quantity,
                "version": self.version + 1,
                "updated_at": occurred_at,
            }
        )
        return type(self).model_validate(payload)

    def apply_sale(
        self,
        *,
        branch_id: UUID,
        product_id: UUID,
        quantity: int,
        sale_id: UUID,
        occurred_at: datetime,
    ) -> InventoryTransition:
        """Apply one sale line and return the new stock snapshot + audit movement."""

        self._check_reference(branch_id=branch_id, product_id=product_id)
        if quantity <= 0:
            raise InventoryError("sale quantity must be positive")
        if quantity > self.available_quantity:
            raise InsufficientStockError(
                f"requested {quantity} units but only {self.available_quantity} are available"
            )

        normalized_time = _normalize_aware_datetime(occurred_at)
        next_item = self._next_snapshot(
            on_hand_quantity=self.on_hand_quantity - quantity,
            occurred_at=normalized_time,
        )
        movement = StockMovement(
            branch_id=self.branch_id,
            product_id=self.product_id,
            movement_type=StockMovementType.SALE,
            quantity_delta=-quantity,
            on_hand_before=self.on_hand_quantity,
            on_hand_after=next_item.on_hand_quantity,
            reserved_before=self.reserved_quantity,
            reserved_after=next_item.reserved_quantity,
            inventory_version_after=next_item.version,
            reference_type="sale",
            reference_id=sale_id,
            occurred_at=normalized_time,
        )
        return InventoryTransition(before=self, after=next_item, movement=movement)

    def apply_restock(
        self,
        *,
        branch_id: UUID,
        product_id: UUID,
        quantity: int,
        restock_id: UUID,
        occurred_at: datetime,
    ) -> InventoryTransition:
        """Apply one received restock line and return the new stock snapshot + movement."""

        self._check_reference(branch_id=branch_id, product_id=product_id)
        if quantity <= 0:
            raise InventoryError("restock quantity must be positive")
        if self.on_hand_quantity + quantity > 100_000_000:
            raise InventoryError("restock would exceed InventoryItem quantity limit")

        normalized_time = _normalize_aware_datetime(occurred_at)
        next_item = self._next_snapshot(
            on_hand_quantity=self.on_hand_quantity + quantity,
            occurred_at=normalized_time,
        )
        movement = StockMovement(
            branch_id=self.branch_id,
            product_id=self.product_id,
            movement_type=StockMovementType.RESTOCK,
            quantity_delta=quantity,
            on_hand_before=self.on_hand_quantity,
            on_hand_after=next_item.on_hand_quantity,
            reserved_before=self.reserved_quantity,
            reserved_after=next_item.reserved_quantity,
            inventory_version_after=next_item.version,
            reference_type="restock",
            reference_id=restock_id,
            occurred_at=normalized_time,
        )
        return InventoryTransition(before=self, after=next_item, movement=movement)


class InventoryTransition(BaseModel):
    """Result of one validated stock mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    before: InventoryItem
    after: InventoryItem
    movement: StockMovement

    @computed_field
    @property
    def reorder_triggered(self) -> bool:
        """True only when this transition crosses into reorder-required state."""

        return not self.before.reorder_required and self.after.reorder_required


def _normalize_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InventoryError("occurred_at must be timezone-aware")
    return value.astimezone(UTC)
