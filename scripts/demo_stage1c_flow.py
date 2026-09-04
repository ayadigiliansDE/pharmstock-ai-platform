"""Small executable walkthrough for the Stage 1C business flow.

Run from the repository root after installing the package:
    python scripts/demo_stage1c_flow.py
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from pharmstock.domain import (
    InventoryItem,
    ReorderPolicy,
    ReorderRequiredEvent,
    Sale,
    SaleChannel,
    SaleLine,
    SaleRecordedEvent,
    StockChangedEvent,
)


def main() -> None:
    branch_id = uuid4()
    product_id = uuid4()

    inventory = InventoryItem(
        branch_id=branch_id,
        product_id=product_id,
        on_hand_quantity=20,
        reorder_policy=ReorderPolicy(reorder_point=15, target_stock_level=50),
    )

    sale = Sale(
        branch_id=branch_id,
        occurred_at=datetime.now(UTC),
        channel=SaleChannel.IN_STORE,
        line_items=(
            SaleLine(
                product_id=product_id,
                quantity=5,
                unit_price=Decimal("25.00"),
            ),
        ),
    )

    sale_event = SaleRecordedEvent.from_sale(sale)
    transition = inventory.apply_sale(
        branch_id=sale.branch_id,
        product_id=product_id,
        quantity=sale.line_items[0].quantity,
        sale_id=sale.sale_id,
        occurred_at=sale.occurred_at,
    )
    stock_event = StockChangedEvent.from_movement(
        transition.movement,
        inventory_item_id=transition.after.inventory_item_id,
        correlation_id=sale_event.correlation_id,
        causation_id=sale_event.event_id,
    )

    print(f"Stock before: {transition.before.on_hand_quantity}")
    print(f"Stock after:  {transition.after.on_hand_quantity}")
    print(f"Available:    {transition.after.available_quantity}")
    print(f"Reorder:      {transition.after.reorder_required}")
    print(f"Sale event:   {sale_event.event_type} v{sale_event.schema_version}")
    print(f"Stock event:  {stock_event.event_type} v{stock_event.schema_version}")

    if transition.reorder_triggered:
        reorder_event = ReorderRequiredEvent.from_inventory(
            transition.after,
            occurred_at=transition.movement.occurred_at,
            correlation_id=sale_event.correlation_id,
            causation_id=stock_event.event_id,
        )
        print(
            "Reorder event: "
            f"{reorder_event.event_type} -> "
            f"{reorder_event.payload.recommended_reorder_quantity} units"
        )


if __name__ == "__main__":
    main()
