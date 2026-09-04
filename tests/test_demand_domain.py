from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from pharmstock.domain import (
    DemandFulfillmentStatus,
    DemandOutcome,
    DemandRequest,
    FEFOAllocation,
    SaleChannel,
)

BRANCH_ID = UUID("11111111-1111-1111-1111-111111111111")
PRODUCT_ID = UUID("22222222-2222-2222-2222-222222222222")
BASKET_ID = UUID("33333333-3333-3333-3333-333333333333")
BATCH_ID = UUID("44444444-4444-4444-4444-444444444444")


def request(quantity: int = 3) -> DemandRequest:
    return DemandRequest(
        basket_id=BASKET_ID,
        branch_id=BRANCH_ID,
        product_id=PRODUCT_ID,
        occurred_at=datetime(2026, 8, 22, 12, 0, tzinfo=UTC),
        channel=SaleChannel.IN_STORE,
        requested_quantity=quantity,
    )


def allocation(quantity: int) -> FEFOAllocation:
    return FEFOAllocation(
        batch_id=BATCH_ID,
        batch_number="B-1",
        expires_on=datetime(2027, 1, 1).date(),
        quantity=quantity,
    )


def test_fully_fulfilled_demand_requires_matching_fefo_quantity() -> None:
    outcome = DemandOutcome(
        demand=request(3),
        fulfilled_quantity=3,
        lost_quantity=0,
        status=DemandFulfillmentStatus.FULFILLED,
        fefo_allocations=(allocation(3),),
    )
    assert outcome.status is DemandFulfillmentStatus.FULFILLED


def test_partial_demand_tracks_lost_units() -> None:
    outcome = DemandOutcome(
        demand=request(4),
        fulfilled_quantity=2,
        lost_quantity=2,
        status=DemandFulfillmentStatus.PARTIAL,
        fefo_allocations=(allocation(2),),
    )
    assert outcome.lost_quantity == 2


def test_stockout_requires_zero_fefo_allocations() -> None:
    outcome = DemandOutcome(
        demand=request(2),
        fulfilled_quantity=0,
        lost_quantity=2,
        status=DemandFulfillmentStatus.STOCKOUT,
    )
    assert outcome.fefo_allocations == ()


def test_status_must_match_quantity_math() -> None:
    with pytest.raises(ValueError):
        DemandOutcome(
            demand=request(3),
            fulfilled_quantity=1,
            lost_quantity=2,
            status=DemandFulfillmentStatus.FULFILLED,
            fefo_allocations=(allocation(1),),
        )


def test_fefo_quantity_must_equal_fulfilled_quantity() -> None:
    with pytest.raises(ValueError):
        DemandOutcome(
            demand=request(3),
            fulfilled_quantity=3,
            lost_quantity=0,
            status=DemandFulfillmentStatus.FULFILLED,
            fefo_allocations=(allocation(2),),
        )


def test_demand_timestamp_is_normalized_to_utc() -> None:
    cairo_like = timezone(timedelta(hours=3))
    item = DemandRequest(
        basket_id=BASKET_ID,
        branch_id=BRANCH_ID,
        product_id=PRODUCT_ID,
        occurred_at=datetime(2026, 8, 22, 15, 0, tzinfo=cairo_like),
        channel=SaleChannel.DELIVERY,
        requested_quantity=1,
    )
    assert item.occurred_at == datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
