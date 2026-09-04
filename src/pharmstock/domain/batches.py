"""Batch-level inventory and FEFO allocation rules.

FEFO (First Expired, First Out) is a domain rule: when multiple usable batches of
one branch/product are available, the batch with the earliest expiry date is
consumed first. Transport and storage technologies must not decide this rule.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pharmstock.domain.inventory import InventoryError


class BatchInventoryError(InventoryError):
    """Base class for batch-level inventory failures."""


class InsufficientUsableBatchStockError(BatchInventoryError):
    """Raised when unexpired batch stock cannot satisfy a requested quantity."""


class BatchReferenceMismatchError(BatchInventoryError):
    """Raised when one FEFO operation mixes more than one branch/product pair."""


class InventoryBatch(BaseModel):
    """Immutable stock snapshot for one physical batch of one branch/product."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    batch_id: UUID = Field(default_factory=uuid4)
    branch_id: UUID
    product_id: UUID
    batch_number: str = Field(min_length=1, max_length=120)
    received_on: date
    expires_on: date
    on_hand_quantity: int = Field(ge=0, le=100_000_000)

    @model_validator(mode="after")
    def expiry_must_follow_receipt(self) -> InventoryBatch:
        if self.expires_on <= self.received_on:
            raise ValueError("expires_on must be after received_on")
        return self

    def is_expired(self, *, as_of: date) -> bool:
        """Return whether the batch is no longer usable on the supplied date."""

        return self.expires_on < as_of


class FEFOAllocation(BaseModel):
    """One quantity allocation from a specific batch in a FEFO plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_id: UUID
    batch_number: str
    expires_on: date
    quantity: int = Field(gt=0)


class FEFOConsumption(BaseModel):
    """Validated result of consuming batch stock using FEFO ordering."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    branch_id: UUID
    product_id: UUID
    requested_quantity: int = Field(gt=0)
    as_of: date
    allocations: tuple[FEFOAllocation, ...]
    updated_batches: tuple[InventoryBatch, ...]

    @property
    def allocated_quantity(self) -> int:
        return sum(item.quantity for item in self.allocations)


def consume_fefo(
    *, batches: Iterable[InventoryBatch], quantity: int, as_of: date
) -> FEFOConsumption:
    """Consume an exact quantity from the earliest-expiring usable batches.

    Expired batches remain in the returned batch snapshots but are never allocated.
    Batches expiring on ``as_of`` are considered usable for that date; a batch is
    expired only when ``expires_on < as_of``.
    """

    if quantity <= 0:
        raise BatchInventoryError("FEFO quantity must be positive")

    snapshots = tuple(batches)
    if not snapshots:
        raise BatchInventoryError("FEFO requires at least one batch")

    batch_ids = {batch.batch_id for batch in snapshots}
    if len(batch_ids) != len(snapshots):
        raise BatchInventoryError("batch_id values must be unique within one FEFO operation")

    branch_ids = {batch.branch_id for batch in snapshots}
    product_ids = {batch.product_id for batch in snapshots}
    if len(branch_ids) != 1 or len(product_ids) != 1:
        raise BatchReferenceMismatchError(
            "all FEFO batches must reference the same branch_id and product_id"
        )

    usable = sorted(
        (
            batch
            for batch in snapshots
            if batch.on_hand_quantity > 0 and not batch.is_expired(as_of=as_of)
        ),
        key=lambda batch: (
            batch.expires_on,
            batch.received_on,
            batch.batch_number,
            str(batch.batch_id),
        ),
    )
    available = sum(batch.on_hand_quantity for batch in usable)
    if quantity > available:
        raise InsufficientUsableBatchStockError(
            f"requested {quantity} units but only {available} unexpired batch units are available"
        )

    remaining = quantity
    consumed_by_batch: dict[UUID, int] = {}
    allocations: list[FEFOAllocation] = []
    for batch in usable:
        if remaining == 0:
            break
        take = min(batch.on_hand_quantity, remaining)
        if take <= 0:
            continue
        consumed_by_batch[batch.batch_id] = take
        allocations.append(
            FEFOAllocation(
                batch_id=batch.batch_id,
                batch_number=batch.batch_number,
                expires_on=batch.expires_on,
                quantity=take,
            )
        )
        remaining -= take

    updated_batches = tuple(
        batch.model_copy(
            update={
                "on_hand_quantity": (
                    batch.on_hand_quantity - consumed_by_batch.get(batch.batch_id, 0)
                )
            }
        )
        for batch in snapshots
    )
    result = FEFOConsumption(
        branch_id=next(iter(branch_ids)),
        product_id=next(iter(product_ids)),
        requested_quantity=quantity,
        as_of=as_of,
        allocations=tuple(allocations),
        updated_batches=updated_batches,
    )
    if result.allocated_quantity != quantity:
        raise AssertionError("FEFO allocation must exactly equal requested quantity")
    return result
