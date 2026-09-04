from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pharmstock.domain import (
    InventoryItem,
    ReorderPolicy,
    ReorderRequiredEvent,
    RestockLine,
    RestockReceipt,
    RestockReceivedEvent,
    Sale,
    SaleChannel,
    SaleLine,
    SaleRecordedEvent,
    StockChangedEvent,
)


def build_sale() -> Sale:
    return Sale(
        branch_id=uuid4(),
        occurred_at=datetime(2026, 8, 22, 12, 0, tzinfo=UTC),
        channel=SaleChannel.IN_STORE,
        line_items=(SaleLine(product_id=uuid4(), quantity=2, unit_price=Decimal("25")),),
    )


def test_sale_recorded_event_has_stable_v1_envelope() -> None:
    sale = build_sale()
    event = SaleRecordedEvent.from_sale(sale)

    assert event.event_type == "sale.recorded"
    assert event.schema_version == "1.0"
    assert event.aggregate_type == "sale"
    assert event.aggregate_id == sale.sale_id
    assert event.correlation_id == sale.sale_id
    assert event.payload.sale == sale


def test_restock_received_event_carries_full_receipt() -> None:
    receipt = RestockReceipt(
        branch_id=uuid4(),
        received_at=datetime(2026, 8, 22, tzinfo=UTC),
        line_items=(
            RestockLine(
                product_id=uuid4(),
                quantity=20,
                unit_cost=Decimal("5"),
                batch_number="B-10",
                expires_on=date(2028, 1, 1),
            ),
        ),
    )

    event = RestockReceivedEvent.from_restock(receipt)

    assert event.event_type == "restock.received"
    assert event.payload.restock.restock_id == receipt.restock_id


def test_stock_changed_and_reorder_events_can_follow_inventory_transition() -> None:
    item = InventoryItem(
        branch_id=uuid4(),
        product_id=uuid4(),
        on_hand_quantity=20,
        reorder_policy=ReorderPolicy(reorder_point=15, target_stock_level=50),
    )
    sale = Sale(
        branch_id=item.branch_id,
        occurred_at=datetime(2026, 8, 22, tzinfo=UTC),
        channel=SaleChannel.IN_STORE,
        line_items=(SaleLine(product_id=item.product_id, quantity=5, unit_price=Decimal("10")),),
    )
    transition = item.apply_sale(
        branch_id=sale.branch_id,
        product_id=item.product_id,
        quantity=5,
        sale_id=sale.sale_id,
        occurred_at=sale.occurred_at,
    )
    sale_event = SaleRecordedEvent.from_sale(sale)
    stock_event = StockChangedEvent.from_movement(
        transition.movement,
        inventory_item_id=transition.after.inventory_item_id,
        correlation_id=sale_event.correlation_id,
        causation_id=sale_event.event_id,
    )
    reorder_event = ReorderRequiredEvent.from_inventory(
        transition.after,
        occurred_at=transition.movement.occurred_at,
        correlation_id=sale_event.correlation_id,
        causation_id=stock_event.event_id,
    )

    assert transition.reorder_triggered is True
    assert stock_event.payload.movement.quantity_delta == -5
    assert stock_event.correlation_id == sale_event.correlation_id
    assert stock_event.causation_id == sale_event.event_id
    assert reorder_event.payload.recommended_reorder_quantity == 35
    assert reorder_event.causation_id == stock_event.event_id


def test_reorder_event_rejects_healthy_inventory() -> None:
    item = InventoryItem(
        branch_id=uuid4(),
        product_id=uuid4(),
        on_hand_quantity=100,
        reorder_policy=ReorderPolicy(reorder_point=10, target_stock_level=50),
    )

    with pytest.raises(ValueError, match="not currently reorder-required"):
        ReorderRequiredEvent.from_inventory(
            item,
            occurred_at=datetime.now(UTC),
            correlation_id=uuid4(),
        )


def test_event_schema_version_is_not_arbitrary() -> None:
    sale = build_sale()
    payload = SaleRecordedEvent.from_sale(sale).model_dump()
    payload["schema_version"] = "2.0"

    with pytest.raises(ValidationError):
        SaleRecordedEvent.model_validate(payload)


def test_event_serializes_to_json_without_custom_encoder() -> None:
    event = SaleRecordedEvent.from_sale(build_sale())

    encoded = event.model_dump_json()

    assert '"event_type":"sale.recorded"' in encoded
    assert '"schema_version":"1.0"' in encoded
