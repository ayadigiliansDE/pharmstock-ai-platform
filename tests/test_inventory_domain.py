from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pharmstock.domain import (
    InsufficientStockError,
    InventoryItem,
    InventoryReferenceMismatchError,
    ReorderPolicy,
    StockMovementType,
)


def build_inventory(*, on_hand: int = 50, reserved: int = 5) -> InventoryItem:
    return InventoryItem(
        branch_id=uuid4(),
        product_id=uuid4(),
        on_hand_quantity=on_hand,
        reserved_quantity=reserved,
        reorder_policy=ReorderPolicy(reorder_point=15, target_stock_level=60),
    )


def test_inventory_available_quantity_excludes_reservations() -> None:
    item = build_inventory(on_hand=50, reserved=5)

    assert item.available_quantity == 45
    assert item.reorder_required is False
    assert item.recommended_reorder_quantity == 15


def test_reserved_quantity_cannot_exceed_on_hand() -> None:
    with pytest.raises(ValidationError):
        build_inventory(on_hand=5, reserved=6)


def test_reorder_target_must_exceed_reorder_point() -> None:
    with pytest.raises(ValidationError):
        ReorderPolicy(reorder_point=20, target_stock_level=20)


def test_sale_returns_new_snapshot_and_negative_movement() -> None:
    item = build_inventory(on_hand=50, reserved=5)
    sale_id = uuid4()
    occurred_at = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)

    result = item.apply_sale(
        branch_id=item.branch_id,
        product_id=item.product_id,
        quantity=10,
        sale_id=sale_id,
        occurred_at=occurred_at,
    )

    assert item.on_hand_quantity == 50
    assert item.version == 1
    assert result.after.on_hand_quantity == 40
    assert result.after.available_quantity == 35
    assert result.after.version == 2
    assert result.movement.movement_type is StockMovementType.SALE
    assert result.movement.quantity_delta == -10
    assert result.movement.reference_id == sale_id


def test_sale_cannot_consume_reserved_stock() -> None:
    item = build_inventory(on_hand=10, reserved=4)

    with pytest.raises(InsufficientStockError):
        item.apply_sale(
            branch_id=item.branch_id,
            product_id=item.product_id,
            quantity=7,
            sale_id=uuid4(),
            occurred_at=datetime.now(UTC),
        )


def test_inventory_operation_rejects_wrong_product_reference() -> None:
    item = build_inventory()

    with pytest.raises(InventoryReferenceMismatchError):
        item.apply_sale(
            branch_id=item.branch_id,
            product_id=uuid4(),
            quantity=1,
            sale_id=uuid4(),
            occurred_at=datetime.now(UTC),
        )


def test_sale_crossing_reorder_point_triggers_reorder_once() -> None:
    item = InventoryItem(
        branch_id=uuid4(),
        product_id=uuid4(),
        on_hand_quantity=20,
        reserved_quantity=0,
        reorder_policy=ReorderPolicy(reorder_point=15, target_stock_level=50),
    )

    result = item.apply_sale(
        branch_id=item.branch_id,
        product_id=item.product_id,
        quantity=5,
        sale_id=uuid4(),
        occurred_at=datetime.now(UTC),
    )

    assert result.after.available_quantity == 15
    assert result.after.reorder_required is True
    assert result.after.recommended_reorder_quantity == 35
    assert result.reorder_triggered is True

    second = result.after.apply_sale(
        branch_id=item.branch_id,
        product_id=item.product_id,
        quantity=1,
        sale_id=uuid4(),
        occurred_at=datetime.now(UTC),
    )
    assert second.reorder_triggered is False


def test_restock_increases_on_hand_and_inventory_version() -> None:
    item = build_inventory(on_hand=12, reserved=2)
    restock_id = uuid4()

    result = item.apply_restock(
        branch_id=item.branch_id,
        product_id=item.product_id,
        quantity=40,
        restock_id=restock_id,
        occurred_at=datetime.now(UTC),
    )

    assert result.after.on_hand_quantity == 52
    assert result.after.reserved_quantity == 2
    assert result.after.version == item.version + 1
    assert result.movement.movement_type is StockMovementType.RESTOCK
    assert result.movement.quantity_delta == 40
    assert result.movement.reference_id == restock_id


def test_inventory_operation_requires_timezone_aware_time() -> None:
    item = build_inventory()

    with pytest.raises(ValueError, match="timezone-aware"):
        item.apply_sale(
            branch_id=item.branch_id,
            product_id=item.product_id,
            quantity=1,
            sale_id=uuid4(),
            occurred_at=datetime(2026, 8, 22, 12, 0),
        )
