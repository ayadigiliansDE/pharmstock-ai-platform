import csv
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError

from pharmstock.domain import (
    InventoryQuantityChangedPayload,
    UnitSaleFulfilledPayload,
)
from pharmstock.streaming import (
    INVENTORY_TOPIC,
    PROCUREMENT_TOPIC,
    SALES_TOPIC,
    KafkaEventProducer,
    KafkaSettings,
    deserialize_event,
    deterministic_event_id,
    event_summary,
    iter_operational_events,
    iter_stage2e_events,
    iter_stage2f1_events,
    serialize_event,
    topic_for_event,
)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _build_artifacts(root: Path) -> tuple[Path, Path]:
    stage2e = root / "stage2e"
    stage2f1 = root / "stage2f1"
    demand_id = "10000000-0000-0000-0000-000000000001"
    basket_id = "10000000-0000-0000-0000-000000000002"
    branch_id = "10000000-0000-0000-0000-000000000003"
    product_id = "10000000-0000-0000-0000-000000000004"
    movement_id = "10000000-0000-0000-0000-000000000005"
    occurred_at = "2026-08-22T10:00:00+00:00"

    _write_csv(
        stage2e / "demand_lines" / "part-00001.csv",
        [
            {
                "demand_id": demand_id,
                "basket_id": basket_id,
                "branch_id": branch_id,
                "branch_code": "CAI-SIM-000001",
                "governorate": "Cairo",
                "branch_scale": "medium",
                "occurred_at": occurred_at,
                "local_date": "2026-08-22",
                "local_hour": 13,
                "channel": "in_store",
                "product_id": product_id,
                "display_name": "Example Product",
                "synthetic_seasonality_profile": "synthetic_stable",
                "requested_quantity": 3,
                "fulfilled_quantity": 2,
                "lost_quantity": 1,
                "fulfillment_status": "partial",
                "on_hand_before": 4,
                "on_hand_after": 2,
                "usable_batch_units_before": 4,
                "reorder_triggered": True,
                "recommended_reorder_quantity": 8,
                "pricing_status": "not_simulated",
                "mapping_status": "synthetic_cross_market_mapping",
            }
        ],
    )
    _write_csv(
        stage2e / "stock_movements" / "part-00001.csv",
        [
            {
                "movement_id": movement_id,
                "demand_id": demand_id,
                "branch_id": branch_id,
                "product_id": product_id,
                "quantity_delta": -2,
                "on_hand_before": 4,
                "on_hand_after": 2,
                "inventory_version_after": 3,
                "occurred_at": occurred_at,
            }
        ],
    )
    _write_csv(
        stage2e / "reorder_triggers" / "part-00001.csv",
        [
            {
                "demand_id": demand_id,
                "branch_id": branch_id,
                "product_id": product_id,
                "occurred_at": occurred_at,
                "available_quantity": 2,
                "reorder_point": 2,
                "target_stock_level": 10,
                "recommended_reorder_quantity": 8,
                "inventory_version": 3,
            }
        ],
    )

    po_id = "20000000-0000-0000-0000-000000000001"
    cycle_id = "20000000-0000-0000-0000-000000000002"
    supplier_id = "20000000-0000-0000-0000-000000000003"
    receipt_id = "20000000-0000-0000-0000-000000000004"
    restock_movement_id = "20000000-0000-0000-0000-000000000005"
    _write_csv(
        stage2f1 / "purchase_orders" / "part-00001.csv",
        [
            {
                "purchase_order_id": po_id,
                "procurement_cycle_id": cycle_id,
                "branch_id": branch_id,
                "branch_code": "CAI-SIM-000001",
                "governorate": "Cairo",
                "supplier_id": supplier_id,
                "supplier_code": "SIM-SUP-001",
                "ordered_at": "2026-08-29T05:00:00+00:00",
                "expected_delivery_on": "2026-08-31",
                "line_count": 1,
                "ordered_units": 8,
                "monetary_values_generated": False,
                "supplier_assignment_status": "synthetic_ranked_panel",
            }
        ],
    )
    _write_csv(
        stage2f1 / "goods_receipts" / "part-00001.csv",
        [
            {
                "receipt_id": receipt_id,
                "purchase_order_id": po_id,
                "branch_id": branch_id,
                "supplier_id": supplier_id,
                "received_at": "2026-08-31T07:00:00+00:00",
                "line_count": 1,
                "received_units": 8,
            }
        ],
    )
    _write_csv(
        stage2f1 / "restock_movements" / "part-00001.csv",
        [
            {
                "movement_id": restock_movement_id,
                "receipt_id": receipt_id,
                "purchase_order_id": po_id,
                "branch_id": branch_id,
                "product_id": product_id,
                "quantity_delta": 8,
                "on_hand_before": 2,
                "on_hand_after": 10,
                "inventory_version_after": 4,
                "occurred_at": "2026-08-31T07:00:00+00:00",
            }
        ],
    )
    return stage2e, stage2f1


def test_stage2e_artifacts_become_causal_sales_inventory_reorder_events(tmp_path: Path) -> None:
    stage2e, _ = _build_artifacts(tmp_path)
    events = tuple(iter_stage2e_events(stage2e))

    assert [event.event_type for event in events] == [
        "sale.units_fulfilled",
        "inventory.quantity_changed",
        "inventory.reorder_required",
    ]
    assert events[1].causation_id == events[0].event_id
    assert events[2].causation_id == events[1].event_id
    expected_correlation = UUID("10000000-0000-0000-0000-000000000001")
    assert all(event.correlation_id == expected_correlation for event in events)


def test_stage2f1_artifacts_become_po_receipt_restock_inventory_events(tmp_path: Path) -> None:
    _, stage2f1 = _build_artifacts(tmp_path)
    events = tuple(iter_stage2f1_events(stage2f1))

    assert [event.event_type for event in events] == [
        "purchase_order.created",
        "goods_receipt.received",
        "restock.applied",
        "inventory.quantity_changed",
    ]
    assert events[1].causation_id == events[0].event_id
    assert events[2].causation_id == events[1].event_id
    assert events[3].causation_id == events[2].event_id


def test_operational_replay_covers_all_three_business_topics(tmp_path: Path) -> None:
    stage2e, stage2f1 = _build_artifacts(tmp_path)
    events = tuple(iter_operational_events(stage2e, stage2f1))
    topics = {topic_for_event(event).name for event in events}

    assert topics == {SALES_TOPIC.name, INVENTORY_TOPIC.name, PROCUREMENT_TOPIC.name}


def test_new_stage3b_contracts_serialize_and_deserialize(tmp_path: Path) -> None:
    stage2e, stage2f1 = _build_artifacts(tmp_path)
    for event in iter_operational_events(stage2e, stage2f1):
        assert deserialize_event(serialize_event(event)) == event


def test_replay_event_ids_are_deterministic_across_repeated_reads(tmp_path: Path) -> None:
    stage2e, stage2f1 = _build_artifacts(tmp_path)
    left = tuple(iter_operational_events(stage2e, stage2f1))
    right = tuple(iter_operational_events(stage2e, stage2f1))

    assert [event.event_id for event in left] == [event.event_id for event in right]
    assert deterministic_event_id("sale.units_fulfilled", "abc") == deterministic_event_id(
        "sale.units_fulfilled", "abc"
    )


def test_event_summary_counts_contracts(tmp_path: Path) -> None:
    stage2e, stage2f1 = _build_artifacts(tmp_path)
    counts = event_summary(iter_operational_events(stage2e, stage2f1))

    assert counts["inventory.quantity_changed"] == 2
    assert counts["sale.units_fulfilled"] == 1
    assert counts["purchase_order.created"] == 1


def test_unit_sale_payload_enforces_requested_equals_fulfilled_plus_lost() -> None:
    with pytest.raises(ValidationError, match="must equal requested_quantity"):
        UnitSaleFulfilledPayload(
            demand_id=UUID("30000000-0000-0000-0000-000000000001"),
            basket_id=UUID("30000000-0000-0000-0000-000000000002"),
            branch_id=UUID("30000000-0000-0000-0000-000000000003"),
            product_id=UUID("30000000-0000-0000-0000-000000000004"),
            channel="in_store",
            requested_quantity=4,
            fulfilled_quantity=2,
            lost_quantity=1,
            fulfillment_status="partial",
        )


def test_inventory_quantity_event_enforces_transition_math() -> None:
    with pytest.raises(ValidationError, match="does not match on-hand transition"):
        InventoryQuantityChangedPayload(
            movement_id=UUID("30000000-0000-0000-0000-000000000005"),
            branch_id=UUID("30000000-0000-0000-0000-000000000003"),
            product_id=UUID("30000000-0000-0000-0000-000000000004"),
            movement_type="sale",
            quantity_delta=-2,
            on_hand_before=10,
            on_hand_after=9,
            inventory_version_after=2,
            reference_id=UUID("30000000-0000-0000-0000-000000000006"),
        )


def test_zero_fulfillment_does_not_create_sale_event(tmp_path: Path) -> None:
    stage2e, _ = _build_artifacts(tmp_path)
    demand_path = stage2e / "demand_lines" / "part-00001.csv"
    rows = list(csv.DictReader(demand_path.open(encoding="utf-8-sig")))
    rows[0]["fulfilled_quantity"] = "0"
    rows[0]["lost_quantity"] = rows[0]["requested_quantity"]
    rows[0]["fulfillment_status"] = "stockout"
    _write_csv(demand_path, rows)

    event_types = [event.event_type for event in iter_stage2e_events(stage2e)]
    assert "sale.units_fulfilled" not in event_types


class _FakeMessage:
    def __init__(self, topic: str, offset: int) -> None:
        self._topic = topic
        self._offset = offset

    def topic(self) -> str:
        return self._topic

    def partition(self) -> int:
        return 0

    def offset(self) -> int:
        return self._offset


class _FakeProducer:
    def __init__(self, _config: dict[str, object]) -> None:
        self.offset = 0

    def produce(self, topic: str, *, on_delivery, **_kwargs) -> None:
        message = _FakeMessage(topic, self.offset)
        self.offset += 1
        on_delivery(None, message)

    def poll(self, _timeout: float) -> None:
        return None

    def flush(self, _timeout: float) -> int:
        return 0


def test_kafka_producer_batches_events_with_one_flush(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stage2e, stage2f1 = _build_artifacts(tmp_path)
    events = tuple(iter_operational_events(stage2e, stage2f1))
    fake_module = SimpleNamespace(Producer=_FakeProducer)
    monkeypatch.setattr("pharmstock.streaming.kafka._load", lambda _name: fake_module)

    producer = KafkaEventProducer(KafkaSettings())
    results = producer.publish_many(events)

    assert len(results) == len(events)
    assert [result.event_id for result in results] == [event.event_id for event in events]
    assert {result.topic for result in results} == {
        SALES_TOPIC.name,
        INVENTORY_TOPIC.name,
        PROCUREMENT_TOPIC.name,
    }
