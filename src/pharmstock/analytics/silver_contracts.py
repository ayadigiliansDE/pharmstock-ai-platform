"""Dependency-light Silver table routing shared with Spark jobs.

This module must remain importable inside the pinned Spark Python runtime without
loading the application domain stack or Pydantic. Keep it to constants and other
stdlib-only helpers.
"""

SILVER_TABLE_BY_EVENT: dict[str, str] = {
    "sale.units_fulfilled": "sales_units_fulfilled",
    "inventory.quantity_changed": "inventory_quantity_changed",
    "inventory.reorder_required": "inventory_reorder_required",
    "purchase_order.created": "purchase_order_created",
    "goods_receipt.received": "goods_receipt_received",
    "restock.applied": "restock_applied",
}

__all__ = ["SILVER_TABLE_BY_EVENT"]
