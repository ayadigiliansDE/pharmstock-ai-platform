"""Shared helpers used only by the visible Stage 3A scripts."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pharmstock.domain import InventoryItem, ReorderPolicy, ReorderRequiredEvent


def build_sample_reorder_event() -> ReorderRequiredEvent:
    item = InventoryItem(
        inventory_item_id=UUID("30000000-0000-0000-0000-000000000001"),
        branch_id=UUID("30000000-0000-0000-0000-000000000002"),
        product_id=UUID("30000000-0000-0000-0000-000000000003"),
        on_hand_quantity=7,
        reorder_policy=ReorderPolicy(reorder_point=10, target_stock_level=30),
        updated_at=datetime(2026, 8, 22, 17, 0, tzinfo=UTC),
    )
    return ReorderRequiredEvent.from_inventory(
        item,
        occurred_at=datetime.now(UTC),
        correlation_id=UUID("30000000-0000-0000-0000-000000000004"),
    )
