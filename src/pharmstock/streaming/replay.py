"""Deterministic bridge from completed simulator artifacts to Kafka domain events.

Stage 3B deliberately replays validated Stage 2E/2F.1 artifacts instead of changing
business logic to publish inline.  This gives a deterministic, inspectable bridge and
keeps the simulator reproducible while Kafka is introduced.  A later outbox stage can
move publication into the live transaction boundary without changing event contracts.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from pharmstock.domain import (
    GoodsReceiptReceivedEvent,
    GoodsReceiptReceivedPayload,
    InventoryQuantityChangedEvent,
    InventoryQuantityChangedPayload,
    PurchaseOrderCreatedEvent,
    PurchaseOrderCreatedPayload,
    ReorderRequiredEvent,
    ReorderRequiredPayload,
    RestockAppliedEvent,
    RestockAppliedPayload,
    UnitSaleFulfilledEvent,
    UnitSaleFulfilledPayload,
)
from pharmstock.streaming.kafka import KafkaDeadLetterProducer, KafkaEventProducer

_EVENT_NAMESPACE = UUID("e51c03ea-ecce-44d4-a4d6-2a6674d66781")
_INVENTORY_AGGREGATE_NAMESPACE = UUID("a9919ca4-bf2c-4776-bf9e-0f078634bf7d")


def deterministic_event_id(event_type: str, source_identity: str) -> UUID:
    return uuid5(_EVENT_NAMESPACE, f"{event_type}|{source_identity}")


def inventory_aggregate_id(branch_id: UUID, product_id: UUID) -> UUID:
    return uuid5(_INVENTORY_AGGREGATE_NAMESPACE, f"{branch_id}|{product_id}")


class DeadLetterRecord(BaseModel):
    """Serializable diagnostic record for rows that cannot become domain events."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dead_letter_id: UUID
    failed_at: datetime
    source_file: str = Field(min_length=1)
    error_type: str = Field(min_length=1)
    error_message: str = Field(min_length=1)
    raw_record: dict[str, str]


@dataclass(frozen=True, slots=True)
class ReplayStats:
    event_candidates_seen: int
    events_built: int
    events_published: int
    dead_letters: int
    event_type_counts: dict[str, int]
    topic_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class ReplayResult:
    output_dir: Path
    manifest_path: Path
    success_marker_path: Path
    stats: ReplayStats
    published_event_ids: tuple[UUID, ...]


def _csv_rows(path: Path) -> Iterator[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def _part_files(path: Path) -> tuple[Path, ...]:
    if not path.exists():
        raise FileNotFoundError(f"required simulator dataset is missing: {path}")
    files = tuple(sorted(path.glob("part-*.csv")))
    if not files:
        raise FileNotFoundError(f"no partition files found under {path}")
    return files


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("artifact timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def _sale_event(row: dict[str, str]) -> UnitSaleFulfilledEvent | None:
    fulfilled = int(row["fulfilled_quantity"])
    if fulfilled <= 0:
        return None
    demand_id = UUID(row["demand_id"])
    return UnitSaleFulfilledEvent(
        event_id=deterministic_event_id("sale.units_fulfilled", row["demand_id"]),
        aggregate_id=demand_id,
        occurred_at=_parse_dt(row["occurred_at"]),
        correlation_id=demand_id,
        payload=UnitSaleFulfilledPayload(
            demand_id=demand_id,
            basket_id=UUID(row["basket_id"]),
            branch_id=UUID(row["branch_id"]),
            product_id=UUID(row["product_id"]),
            channel=row["channel"],
            requested_quantity=int(row["requested_quantity"]),
            fulfilled_quantity=fulfilled,
            lost_quantity=int(row["lost_quantity"]),
            fulfillment_status=row["fulfillment_status"],
        ),
    )


def _sale_inventory_event(row: dict[str, str]) -> InventoryQuantityChangedEvent:
    demand_id = UUID(row["demand_id"])
    branch_id = UUID(row["branch_id"])
    product_id = UUID(row["product_id"])
    sale_event_id = deterministic_event_id("sale.units_fulfilled", row["demand_id"])
    return InventoryQuantityChangedEvent(
        event_id=deterministic_event_id("inventory.quantity_changed", row["movement_id"]),
        aggregate_id=inventory_aggregate_id(branch_id, product_id),
        occurred_at=_parse_dt(row["occurred_at"]),
        correlation_id=demand_id,
        causation_id=sale_event_id,
        payload=InventoryQuantityChangedPayload(
            movement_id=UUID(row["movement_id"]),
            branch_id=branch_id,
            product_id=product_id,
            movement_type="sale",
            quantity_delta=int(row["quantity_delta"]),
            on_hand_before=int(row["on_hand_before"]),
            on_hand_after=int(row["on_hand_after"]),
            inventory_version_after=int(row["inventory_version_after"]),
            reference_id=demand_id,
        ),
    )


def _reorder_event(
    row: dict[str, str], *, movement_id: str | None = None
) -> ReorderRequiredEvent:
    demand_id = UUID(row["demand_id"])
    branch_id = UUID(row["branch_id"])
    product_id = UUID(row["product_id"])
    inventory_id = inventory_aggregate_id(branch_id, product_id)
    stock_event_id = (
        deterministic_event_id("inventory.quantity_changed", movement_id)
        if movement_id is not None
        else None
    )
    return ReorderRequiredEvent(
        event_id=deterministic_event_id(
            "inventory.reorder_required", f"{row['demand_id']}|{row['product_id']}"
        ),
        aggregate_id=inventory_id,
        occurred_at=_parse_dt(row["occurred_at"]),
        correlation_id=demand_id,
        causation_id=stock_event_id,
        payload=ReorderRequiredPayload(
            branch_id=branch_id,
            product_id=product_id,
            available_quantity=int(row["available_quantity"]),
            reorder_point=int(row["reorder_point"]),
            target_stock_level=int(row["target_stock_level"]),
            recommended_reorder_quantity=int(row["recommended_reorder_quantity"]),
            inventory_version=int(row["inventory_version"]),
        ),
    )


def _purchase_order_event(row: dict[str, str]) -> PurchaseOrderCreatedEvent:
    po_id = UUID(row["purchase_order_id"])
    cycle_id = UUID(row["procurement_cycle_id"])
    return PurchaseOrderCreatedEvent(
        event_id=deterministic_event_id("purchase_order.created", row["purchase_order_id"]),
        aggregate_id=po_id,
        occurred_at=_parse_dt(row["ordered_at"]),
        correlation_id=cycle_id,
        payload=PurchaseOrderCreatedPayload(
            purchase_order_id=po_id,
            procurement_cycle_id=cycle_id,
            branch_id=UUID(row["branch_id"]),
            supplier_id=UUID(row["supplier_id"]),
            expected_delivery_on=datetime.fromisoformat(row["expected_delivery_on"]).date(),
            line_count=int(row["line_count"]),
            ordered_units=int(row["ordered_units"]),
        ),
    )


def _receipt_event(
    row: dict[str, str], *, procurement_cycle_id: UUID
) -> GoodsReceiptReceivedEvent:
    receipt_id = UUID(row["receipt_id"])
    po_id = UUID(row["purchase_order_id"])
    return GoodsReceiptReceivedEvent(
        event_id=deterministic_event_id("goods_receipt.received", row["receipt_id"]),
        aggregate_id=receipt_id,
        occurred_at=_parse_dt(row["received_at"]),
        correlation_id=procurement_cycle_id,
        causation_id=deterministic_event_id("purchase_order.created", row["purchase_order_id"]),
        payload=GoodsReceiptReceivedPayload(
            receipt_id=receipt_id,
            purchase_order_id=po_id,
            branch_id=UUID(row["branch_id"]),
            supplier_id=UUID(row["supplier_id"]),
            line_count=int(row["line_count"]),
            received_units=int(row["received_units"]),
        ),
    )


def _restock_event(
    row: dict[str, str], *, procurement_cycle_id: UUID
) -> RestockAppliedEvent:
    branch_id = UUID(row["branch_id"])
    product_id = UUID(row["product_id"])
    receipt_id = UUID(row["receipt_id"])
    return RestockAppliedEvent(
        event_id=deterministic_event_id("restock.applied", row["movement_id"]),
        aggregate_id=inventory_aggregate_id(branch_id, product_id),
        occurred_at=_parse_dt(row["occurred_at"]),
        correlation_id=procurement_cycle_id,
        causation_id=deterministic_event_id("goods_receipt.received", row["receipt_id"]),
        payload=RestockAppliedPayload(
            movement_id=UUID(row["movement_id"]),
            receipt_id=receipt_id,
            purchase_order_id=UUID(row["purchase_order_id"]),
            branch_id=branch_id,
            product_id=product_id,
            quantity=int(row["quantity_delta"]),
            on_hand_before=int(row["on_hand_before"]),
            on_hand_after=int(row["on_hand_after"]),
            inventory_version_after=int(row["inventory_version_after"]),
        ),
    )


def _restock_inventory_event(
    row: dict[str, str], *, procurement_cycle_id: UUID
) -> InventoryQuantityChangedEvent:
    branch_id = UUID(row["branch_id"])
    product_id = UUID(row["product_id"])
    receipt_id = UUID(row["receipt_id"])
    return InventoryQuantityChangedEvent(
        event_id=deterministic_event_id(
            "inventory.quantity_changed", f"restock|{row['movement_id']}"
        ),
        aggregate_id=inventory_aggregate_id(branch_id, product_id),
        occurred_at=_parse_dt(row["occurred_at"]),
        correlation_id=procurement_cycle_id,
        causation_id=deterministic_event_id("restock.applied", row["movement_id"]),
        payload=InventoryQuantityChangedPayload(
            movement_id=UUID(row["movement_id"]),
            branch_id=branch_id,
            product_id=product_id,
            movement_type="restock",
            quantity_delta=int(row["quantity_delta"]),
            on_hand_before=int(row["on_hand_before"]),
            on_hand_after=int(row["on_hand_after"]),
            inventory_version_after=int(row["inventory_version_after"]),
            reference_id=receipt_id,
        ),
    )


def iter_stage2e_events(stage2e_dir: Path) -> Iterator[Any]:
    """Yield sales/inventory/reorder events in branch-partition causal order."""

    demand_parts = _part_files(stage2e_dir / "demand_lines")
    movement_parts = _part_files(stage2e_dir / "stock_movements")
    reorder_parts = _part_files(stage2e_dir / "reorder_triggers")
    if not (len(demand_parts) == len(movement_parts) == len(reorder_parts)):
        raise ValueError("Stage 2E partition counts do not align")

    for demand_path, movement_path, reorder_path in zip(
        demand_parts, movement_parts, reorder_parts, strict=True
    ):
        movements = {row["demand_id"]: row for row in _csv_rows(movement_path)}
        reorders = {row["demand_id"]: row for row in _csv_rows(reorder_path)}
        for row in _csv_rows(demand_path):
            sale = _sale_event(row)
            if sale is not None:
                yield sale
            movement_row = movements.get(row["demand_id"])
            if movement_row is not None:
                yield _sale_inventory_event(movement_row)
            reorder_row = reorders.get(row["demand_id"])
            if reorder_row is not None:
                yield _reorder_event(
                    reorder_row,
                    movement_id=(
                        movement_row["movement_id"] if movement_row is not None else None
                    ),
                )


def iter_stage2f1_events(stage2f1_dir: Path) -> Iterator[Any]:
    """Yield PO -> receipt -> restock -> inventory events in causal order."""

    po_parts = _part_files(stage2f1_dir / "purchase_orders")
    receipt_parts = _part_files(stage2f1_dir / "goods_receipts")
    restock_parts = _part_files(stage2f1_dir / "restock_movements")
    if not (len(po_parts) == len(receipt_parts) == len(restock_parts)):
        raise ValueError("Stage 2F.1 partition counts do not align")

    for po_path, receipt_path, restock_path in zip(
        po_parts, receipt_parts, restock_parts, strict=True
    ):
        receipt_by_po = {row["purchase_order_id"]: row for row in _csv_rows(receipt_path)}
        restock_by_receipt: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in _csv_rows(restock_path):
            restock_by_receipt[row["receipt_id"]].append(row)

        for po_row in _csv_rows(po_path):
            cycle_id = UUID(po_row["procurement_cycle_id"])
            yield _purchase_order_event(po_row)
            receipt_row = receipt_by_po.get(po_row["purchase_order_id"])
            if receipt_row is None:
                continue
            yield _receipt_event(receipt_row, procurement_cycle_id=cycle_id)
            for restock_row in restock_by_receipt[receipt_row["receipt_id"]]:
                yield _restock_event(restock_row, procurement_cycle_id=cycle_id)
                yield _restock_inventory_event(restock_row, procurement_cycle_id=cycle_id)


def iter_operational_events(stage2e_dir: Path, stage2f1_dir: Path) -> Iterator[Any]:
    yield from iter_stage2e_events(stage2e_dir)
    yield from iter_stage2f1_events(stage2f1_dir)


def replay_operational_events(
    *,
    producer: KafkaEventProducer,
    dead_letter_producer: KafkaDeadLetterProducer,
    stage2e_dir: Path,
    stage2f1_dir: Path,
    output_dir: Path,
    stage2e_event_limit: int | None = None,
    stage2f1_event_limit: int | None = None,
    batch_size: int = 500,
) -> ReplayResult:
    """Publish deterministic simulator events in bounded Kafka batches.

    Limits are per source stage so a visible checkpoint can always include both
    demand/inventory events and procurement/restock events.
    """

    for name, value in (
        ("stage2e_event_limit", stage2e_event_limit),
        ("stage2f1_event_limit", stage2f1_event_limit),
    ):
        if value is not None and value <= 0:
            raise ValueError(f"{name} must be positive when provided")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "_SUCCESS").unlink(missing_ok=True)

    source_rows = 0
    built = 0
    published = 0
    dead_letters = 0
    event_counts: Counter[str] = Counter()
    topic_counts: Counter[str] = Counter()
    published_ids: list[UUID] = []
    batch: list[Any] = []

    def flush_batch() -> None:
        nonlocal published
        if not batch:
            return
        results = producer.publish_many(tuple(batch))
        published += len(results)
        for event, result in zip(batch, results, strict=True):
            published_ids.append(result.event_id)
            event_counts[event.event_type] += 1
            topic_counts[result.topic] += 1
        batch.clear()

    def publish_source(events: Iterator[Any], limit: int | None) -> None:
        nonlocal source_rows, built, dead_letters
        emitted = 0
        while limit is None or emitted < limit:
            try:
                event = next(events)
            except StopIteration:
                break
            except Exception as exc:
                source_rows += 1
                dead_letters += 1
                record = DeadLetterRecord(
                    dead_letter_id=deterministic_event_id(
                        "dead_letter", f"{source_rows}|{type(exc).__name__}|{exc}"
                    ),
                    failed_at=datetime.now(UTC),
                    source_file="simulator-artifact-replay",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    raw_record={"source_sequence": str(source_rows)},
                )
                dead_letter_producer.publish(record.model_dump_json().encode("utf-8"))
                continue
            source_rows += 1
            batch.append(event)
            built += 1
            emitted += 1
            if len(batch) >= batch_size:
                flush_batch()

    publish_source(iter_stage2e_events(stage2e_dir), stage2e_event_limit)
    publish_source(iter_stage2f1_events(stage2f1_dir), stage2f1_event_limit)
    flush_batch()

    stats = ReplayStats(
        event_candidates_seen=source_rows,
        events_built=built,
        events_published=published,
        dead_letters=dead_letters,
        event_type_counts=dict(sorted(event_counts.items())),
        topic_counts=dict(sorted(topic_counts.items())),
    )
    manifest_path = output_dir / "stream_manifest.json"
    manifest = {
        "stage": "3B",
        "bridge_mode": "deterministic_artifact_replay",
        "stage2e_input": str(stage2e_dir.resolve()),
        "stage2f1_input": str(stage2f1_dir.resolve()),
        "stage2e_event_limit": stage2e_event_limit,
        "stage2f1_event_limit": stage2f1_event_limit,
        "batch_size": batch_size,
        "event_candidates_seen": stats.event_candidates_seen,
        "events_built": stats.events_built,
        "events_published": stats.events_published,
        "dead_letters": stats.dead_letters,
        "event_type_counts": stats.event_type_counts,
        "topic_counts": stats.topic_counts,
        "event_identity": "deterministic_uuid5_from_source_identity",
        "monetary_values_generated": False,
        "completion_marker": "_SUCCESS",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    success = output_dir / "_SUCCESS"
    success.write_text("STAGE_3B_REPLAY_COMPLETE\n", encoding="utf-8")
    return ReplayResult(
        output_dir=output_dir,
        manifest_path=manifest_path,
        success_marker_path=success,
        stats=stats,
        published_event_ids=tuple(published_ids),
    )

def event_summary(events: Iterable[Any]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for event in events:
        counts[event.event_type] += 1
    return dict(sorted(counts.items()))
