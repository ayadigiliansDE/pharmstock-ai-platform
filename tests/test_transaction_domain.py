from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pharmstock.domain import RestockLine, RestockReceipt, Sale, SaleChannel, SaleLine


def test_sale_totals_use_decimal_and_discount() -> None:
    sale = Sale(
        branch_id=uuid4(),
        occurred_at=datetime(2026, 8, 22, 15, 0, tzinfo=timezone(timedelta(hours=3))),
        channel=SaleChannel.IN_STORE,
        currency_code="egp",
        line_items=(
            SaleLine(
                product_id=uuid4(),
                quantity=2,
                unit_price=Decimal("25.50"),
                discount_amount=Decimal("1.00"),
            ),
            SaleLine(
                product_id=uuid4(),
                quantity=1,
                unit_price=Decimal("80.00"),
            ),
        ),
    )

    assert sale.currency_code == "EGP"
    assert sale.total_quantity == 3
    assert sale.gross_amount == Decimal("131.00")
    assert sale.discount_amount == Decimal("1.00")
    assert sale.net_amount == Decimal("130.00")
    assert sale.occurred_at.utcoffset() == timedelta(0)


def test_sale_rejects_discount_above_line_gross() -> None:
    with pytest.raises(ValidationError):
        SaleLine(
            product_id=uuid4(),
            quantity=1,
            unit_price=Decimal("10"),
            discount_amount=Decimal("11"),
        )


def test_sale_rejects_duplicate_product_lines() -> None:
    product_id = uuid4()

    with pytest.raises(ValidationError, match="product_id"):
        Sale(
            branch_id=uuid4(),
            occurred_at=datetime.now(UTC),
            channel=SaleChannel.DELIVERY,
            line_items=(
                SaleLine(product_id=product_id, quantity=1, unit_price=Decimal("10")),
                SaleLine(product_id=product_id, quantity=2, unit_price=Decimal("10")),
            ),
        )


def test_sale_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError):
        Sale(
            branch_id=uuid4(),
            occurred_at=datetime(2026, 8, 22, 12, 0),
            channel=SaleChannel.IN_STORE,
            line_items=(
                SaleLine(product_id=uuid4(), quantity=1, unit_price=Decimal("10")),
            ),
        )


def test_restock_tracks_batch_expiry_and_total_cost() -> None:
    receipt = RestockReceipt(
        branch_id=uuid4(),
        received_at=datetime(2026, 8, 22, 10, 0, tzinfo=UTC),
        currency_code="EGP",
        supplier_reference="SUP-001",
        purchase_order_reference="PO-1001",
        line_items=(
            RestockLine(
                product_id=uuid4(),
                quantity=100,
                unit_cost=Decimal("12.25"),
                batch_number="BATCH-A1",
                expires_on=date(2027, 12, 31),
            ),
        ),
    )

    assert receipt.total_quantity == 100
    assert receipt.total_cost == Decimal("1225.00")
    assert receipt.line_items[0].batch_number == "BATCH-A1"


def test_restock_rejects_expired_batch() -> None:
    with pytest.raises(ValidationError, match="expired"):
        RestockReceipt(
            branch_id=uuid4(),
            received_at=datetime(2026, 8, 22, 10, 0, tzinfo=UTC),
            line_items=(
                RestockLine(
                    product_id=uuid4(),
                    quantity=10,
                    unit_cost=Decimal("1"),
                    batch_number="OLD-01",
                    expires_on=date(2026, 8, 22),
                ),
            ),
        )


def test_restock_rejects_duplicate_product_batch_pair() -> None:
    product_id = uuid4()
    common = {
        "product_id": product_id,
        "quantity": 10,
        "unit_cost": Decimal("1"),
        "batch_number": "B-1",
        "expires_on": date(2027, 1, 1),
    }

    with pytest.raises(ValidationError, match="batch_number"):
        RestockReceipt(
            branch_id=uuid4(),
            received_at=datetime(2026, 8, 22, tzinfo=UTC),
            line_items=(RestockLine(**common), RestockLine(**common)),
        )
