from datetime import date
from uuid import UUID

import pytest

from pharmstock.domain import (
    BatchReferenceMismatchError,
    InsufficientUsableBatchStockError,
    InventoryBatch,
    consume_fefo,
)

BRANCH_ID = UUID("11111111-1111-1111-1111-111111111111")
PRODUCT_ID = UUID("22222222-2222-2222-2222-222222222222")


def batch(
    number: str, *, expires: str, quantity: int, product_id: UUID = PRODUCT_ID
) -> InventoryBatch:
    return InventoryBatch(
        batch_id=UUID(int=int(number)),
        branch_id=BRANCH_ID,
        product_id=product_id,
        batch_number=f"B-{number}",
        received_on=date(2026, 1, 1),
        expires_on=date.fromisoformat(expires),
        on_hand_quantity=quantity,
    )


def test_fefo_consumes_earliest_expiry_first() -> None:
    batches = (
        batch("1", expires="2027-12-31", quantity=10),
        batch("2", expires="2026-12-31", quantity=5),
        batch("3", expires="2027-06-30", quantity=8),
    )
    result = consume_fefo(batches=batches, quantity=9, as_of=date(2026, 8, 22))
    assert [(row.batch_number, row.quantity) for row in result.allocations] == [
        ("B-2", 5),
        ("B-3", 4),
    ]
    remaining = {row.batch_number: row.on_hand_quantity for row in result.updated_batches}
    assert remaining == {"B-1": 10, "B-2": 0, "B-3": 4}


def test_expired_batches_are_never_allocated() -> None:
    batches = (
        batch("1", expires="2026-08-01", quantity=100),
        batch("2", expires="2026-09-01", quantity=4),
    )
    result = consume_fefo(batches=batches, quantity=4, as_of=date(2026, 8, 22))
    assert [row.batch_number for row in result.allocations] == ["B-2"]
    assert result.updated_batches[0].on_hand_quantity == 100


def test_batch_expiring_today_is_still_usable() -> None:
    result = consume_fefo(
        batches=(batch("1", expires="2026-08-22", quantity=2),),
        quantity=2,
        as_of=date(2026, 8, 22),
    )
    assert result.allocated_quantity == 2


def test_insufficient_unexpired_stock_is_rejected() -> None:
    batches = (
        batch("1", expires="2026-08-01", quantity=100),
        batch("2", expires="2026-09-01", quantity=3),
    )
    with pytest.raises(InsufficientUsableBatchStockError):
        consume_fefo(batches=batches, quantity=4, as_of=date(2026, 8, 22))


def test_mixed_product_batches_are_rejected() -> None:
    other_product = UUID("33333333-3333-3333-3333-333333333333")
    with pytest.raises(BatchReferenceMismatchError):
        consume_fefo(
            batches=(
                batch("1", expires="2027-01-01", quantity=3),
                batch("2", expires="2027-02-01", quantity=3, product_id=other_product),
            ),
            quantity=1,
            as_of=date(2026, 8, 22),
        )


def test_fefo_does_not_mutate_original_batches() -> None:
    original = batch("1", expires="2027-01-01", quantity=5)
    result = consume_fefo(batches=(original,), quantity=2, as_of=date(2026, 8, 22))
    assert original.on_hand_quantity == 5
    assert result.updated_batches[0].on_hand_quantity == 3


def test_non_positive_quantity_is_rejected() -> None:
    with pytest.raises(ValueError):
        consume_fefo(
            batches=(batch("1", expires="2027-01-01", quantity=5),),
            quantity=0,
            as_of=date(2026, 8, 22),
        )


def test_batch_expiry_must_follow_receipt() -> None:
    with pytest.raises(ValueError):
        InventoryBatch(
            branch_id=BRANCH_ID,
            product_id=PRODUCT_ID,
            batch_number="BAD",
            received_on=date(2026, 9, 1),
            expires_on=date(2026, 8, 1),
            on_hand_quantity=1,
        )


def test_duplicate_batch_ids_are_rejected() -> None:
    first = batch("1", expires="2027-01-01", quantity=2)
    duplicate = first.model_copy(
        update={"batch_number": "B-DUP", "expires_on": date(2027, 2, 1)}
    )
    with pytest.raises(ValueError):
        consume_fefo(
            batches=(first, duplicate),
            quantity=1,
            as_of=date(2026, 8, 22),
        )
