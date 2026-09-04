from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from pharmstock.domain import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    SupplierProfile,
    SupplierType,
)

SUPPLIER_ID = UUID("10000000-0000-0000-0000-000000000001")
BRANCH_ID = UUID("20000000-0000-0000-0000-000000000001")
PRODUCT_A = UUID("30000000-0000-0000-0000-000000000001")
PRODUCT_B = UUID("30000000-0000-0000-0000-000000000002")
CYCLE_ID = UUID("40000000-0000-0000-0000-000000000001")
PO_ID = UUID("50000000-0000-0000-0000-000000000001")


def test_supplier_codes_and_regions_are_normalized() -> None:
    supplier = SupplierProfile(
        supplier_id=SUPPLIER_ID,
        supplier_code=" sim-sup-01 ",
        display_name="Synthetic Supplier",
        supplier_type=SupplierType.REGIONAL_WHOLESALER,
        market_code="eg",
        base_lead_time_days=2,
        service_regions=("UPPER_EGYPT",),
    )
    assert supplier.supplier_code == "SIM-SUP-01"
    assert supplier.market_code == "EG"
    assert supplier.service_regions == ("upper_egypt",)
    assert supplier.synthetic_record is True


def test_supplier_rejects_duplicate_regions() -> None:
    with pytest.raises(ValidationError):
        SupplierProfile(
            supplier_id=SUPPLIER_ID,
            supplier_code="SIM-SUP-01",
            display_name="Synthetic Supplier",
            supplier_type=SupplierType.NATIONAL_DISTRIBUTOR,
            base_lead_time_days=2,
            service_regions=("urban_governorates", "URBAN_GOVERNORATES"),
        )


def test_purchase_order_rejects_duplicate_products() -> None:
    line = PurchaseOrderLine(product_id=PRODUCT_A, ordered_quantity=5)
    with pytest.raises(ValidationError):
        PurchaseOrder(
            purchase_order_id=PO_ID,
            branch_id=BRANCH_ID,
            supplier_id=SUPPLIER_ID,
            ordered_at=datetime(2026, 8, 29, 8, tzinfo=UTC),
            expected_delivery_on=date(2026, 8, 31),
            line_items=(line, line),
            procurement_cycle_id=CYCLE_ID,
        )


def test_purchase_order_rejects_delivery_before_order_date() -> None:
    with pytest.raises(ValidationError):
        PurchaseOrder(
            purchase_order_id=PO_ID,
            branch_id=BRANCH_ID,
            supplier_id=SUPPLIER_ID,
            ordered_at=datetime(2026, 8, 29, 8, tzinfo=UTC),
            expected_delivery_on=date(2026, 8, 28),
            line_items=(PurchaseOrderLine(product_id=PRODUCT_A, ordered_quantity=5),),
            procurement_cycle_id=CYCLE_ID,
        )


def test_purchase_order_total_quantity() -> None:
    order = PurchaseOrder(
        purchase_order_id=PO_ID,
        branch_id=BRANCH_ID,
        supplier_id=SUPPLIER_ID,
        ordered_at=datetime(2026, 8, 29, 8, tzinfo=UTC),
        expected_delivery_on=date(2026, 8, 31),
        line_items=(
            PurchaseOrderLine(product_id=PRODUCT_A, ordered_quantity=5),
            PurchaseOrderLine(product_id=PRODUCT_B, ordered_quantity=7),
        ),
        procurement_cycle_id=CYCLE_ID,
    )
    assert order.total_ordered_quantity == 12


def test_goods_receipt_rejects_expired_batch() -> None:
    with pytest.raises(ValidationError):
        GoodsReceipt(
            purchase_order_id=PO_ID,
            branch_id=BRANCH_ID,
            supplier_id=SUPPLIER_ID,
            received_at=datetime(2026, 8, 31, 8, tzinfo=UTC),
            line_items=(
                GoodsReceiptLine(
                    product_id=PRODUCT_A,
                    received_quantity=5,
                    batch_number="B-001",
                    expires_on=date(2026, 8, 31),
                ),
            ),
        )
