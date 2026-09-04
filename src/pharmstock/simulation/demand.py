"""Bounded-memory synthetic demand and unit-sales simulation for Stage 2E.

The engine consumes the completed Stage 2D partitioned inventory dataset one branch
at a time. Demand is intentionally synthetic but structured: branch scale, pharmacy
type, opening hours, weekday, hour-of-day, long-tail product popularity and a
clearly-labeled synthetic seasonality cohort all influence requested unit demand.

No market prices or revenue are generated in this stage.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from bisect import bisect_left
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from itertools import groupby
from pathlib import Path
from typing import TextIO
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from pharmstock.domain import (
    DemandFulfillmentStatus,
    DemandOutcome,
    DemandRequest,
    InventoryBatch,
    InventoryItem,
    PharmacyBranch,
    PharmacyScale,
    PharmacyType,
    ReorderPolicy,
    SaleChannel,
    ServiceMode,
    Weekday,
    consume_fefo,
)
from pharmstock.simulation.network import PharmacyNetworkGenerator

_DEMAND_NAMESPACE = UUID("c2081327-1e0c-4b4e-8148-4535f3012214")
_CAIRO = ZoneInfo("Africa/Cairo")
_WEEKDAYS = tuple(Weekday)


@dataclass(frozen=True, slots=True)
class DemandSimulationPolicy:
    """Explicit synthetic assumptions used to create learnable demand patterns.

    These values are not measured Egyptian pharmacy-market statistics. They are
    configurable simulation parameters and are persisted in the Stage 2E manifest.
    """

    small_daily_baskets: float = 70.0
    medium_daily_baskets: float = 145.0
    large_daily_baskets: float = 270.0
    flagship_daily_baskets: float = 430.0
    hospital_multiplier: float = 1.18
    fulfillment_center_multiplier: float = 1.22
    clinic_multiplier: float = 0.82
    product_popularity_exponent: float = 0.78
    max_lines_per_basket: int = 4
    max_units_per_line: int = 4

    def validate(self) -> None:
        if min(
            self.small_daily_baskets,
            self.medium_daily_baskets,
            self.large_daily_baskets,
            self.flagship_daily_baskets,
        ) <= 0:
            raise ValueError("daily basket assumptions must be positive")
        if min(
            self.hospital_multiplier,
            self.fulfillment_center_multiplier,
            self.clinic_multiplier,
        ) <= 0:
            raise ValueError("pharmacy-type multipliers must be positive")
        if not 0 < self.product_popularity_exponent <= 2:
            raise ValueError("product_popularity_exponent must be in (0, 2]")
        if not 1 <= self.max_lines_per_basket <= 4:
            raise ValueError("max_lines_per_basket must be in [1, 4]")
        if not 1 <= self.max_units_per_line <= 4:
            raise ValueError("max_units_per_line must be in [1, 4]")

    def daily_baskets(self, branch: PharmacyBranch) -> float:
        base = {
            PharmacyScale.SMALL: self.small_daily_baskets,
            PharmacyScale.MEDIUM: self.medium_daily_baskets,
            PharmacyScale.LARGE: self.large_daily_baskets,
            PharmacyScale.FLAGSHIP: self.flagship_daily_baskets,
        }[branch.scale]
        multiplier = {
            PharmacyType.COMMUNITY: 1.0,
            PharmacyType.HOSPITAL: self.hospital_multiplier,
            PharmacyType.CLINIC: self.clinic_multiplier,
            PharmacyType.FULFILLMENT_CENTER: self.fulfillment_center_multiplier,
        }[branch.pharmacy_type]
        return base * multiplier


@dataclass(frozen=True, slots=True)
class DemandLineRow:
    demand_id: str
    basket_id: str
    branch_id: str
    branch_code: str
    governorate: str
    branch_scale: str
    occurred_at: str
    local_date: str
    local_hour: int
    channel: str
    product_id: str
    display_name: str
    synthetic_seasonality_profile: str
    requested_quantity: int
    fulfilled_quantity: int
    lost_quantity: int
    fulfillment_status: str
    on_hand_before: int
    on_hand_after: int
    usable_batch_units_before: int
    reorder_triggered: bool
    recommended_reorder_quantity: int
    pricing_status: str
    mapping_status: str


@dataclass(frozen=True, slots=True)
class BatchAllocationRow:
    demand_id: str
    branch_id: str
    product_id: str
    batch_id: str
    batch_number: str
    expires_on: str
    allocated_quantity: int


@dataclass(frozen=True, slots=True)
class StockMovementRow:
    movement_id: str
    demand_id: str
    branch_id: str
    product_id: str
    quantity_delta: int
    on_hand_before: int
    on_hand_after: int
    inventory_version_after: int
    occurred_at: str


@dataclass(frozen=True, slots=True)
class ReorderTriggerRow:
    demand_id: str
    branch_id: str
    product_id: str
    occurred_at: str
    available_quantity: int
    reorder_point: int
    target_stock_level: int
    recommended_reorder_quantity: int
    inventory_version: int


@dataclass(frozen=True, slots=True)
class DailyBranchKpiRow:
    branch_id: str
    branch_code: str
    governorate: str
    branch_scale: str
    local_date: str
    baskets: int
    demand_lines: int
    requested_units: int
    fulfilled_units: int
    lost_units: int
    fulfilled_lines: int
    partial_lines: int
    stockout_lines: int
    reorder_triggers: int
    unit_fulfillment_rate_pct: float


@dataclass(frozen=True, slots=True)
class DemandSimulationResult:
    output_dir: Path
    manifest_path: Path
    success_marker_path: Path
    daily_kpi_path: Path
    branch_count: int
    simulated_days: int
    baskets: int
    demand_lines: int
    requested_units: int
    fulfilled_units: int
    lost_units: int
    reorder_triggers: int
    partition_count: int


@dataclass(slots=True)
class _BranchState:
    branch: PharmacyBranch
    inventory: dict[UUID, InventoryItem]
    inventory_source_rows: dict[UUID, dict[str, str]]
    batches: dict[UUID, tuple[InventoryBatch, ...]]
    product_names: dict[UUID, str]


@dataclass(slots=True)
class _DailyAccumulator:
    baskets: int = 0
    demand_lines: int = 0
    requested_units: int = 0
    fulfilled_units: int = 0
    lost_units: int = 0
    fulfilled_lines: int = 0
    partial_lines: int = 0
    stockout_lines: int = 0
    reorder_triggers: int = 0


@dataclass(frozen=True, slots=True)
class _WeightedProductSampler:
    population: tuple[UUID, ...]
    cumulative_weights: tuple[float, ...]
    total_weight: float

    def choose(self, rng: random.Random) -> UUID:
        point = rng.random() * self.total_weight
        index = bisect_left(self.cumulative_weights, point)
        if index >= len(self.population):
            index = len(self.population) - 1
        return self.population[index]


@dataclass(slots=True)
class _OutputPartition:
    stack: ExitStack
    demand_handle: TextIO
    allocation_handle: TextIO
    movement_handle: TextIO
    reorder_handle: TextIO
    ending_inventory_handle: TextIO
    ending_batch_handle: TextIO
    demand_writer: csv.DictWriter
    allocation_writer: csv.DictWriter
    movement_writer: csv.DictWriter
    reorder_writer: csv.DictWriter
    ending_inventory_writer: csv.DictWriter
    ending_batch_writer: csv.DictWriter

    def close(self) -> None:
        self.stack.close()


def branch_is_open(branch: PharmacyBranch, local_dt: datetime) -> bool:
    """Return whether a branch is open at a timezone-local timestamp.

    Overnight schedules are evaluated against both the current day's opening and
    the previous day's schedule for the after-midnight tail.
    """

    if local_dt.tzinfo is None or local_dt.utcoffset() is None:
        raise ValueError("local_dt must be timezone-aware")

    schedule = {entry.weekday: entry for entry in branch.operating_profile.schedule}
    weekday = _WEEKDAYS[local_dt.weekday()]
    previous_weekday = _WEEKDAYS[(local_dt.weekday() - 1) % 7]
    current = schedule[weekday]
    previous = schedule[previous_weekday]
    clock = local_dt.timetz().replace(tzinfo=None)

    if current.is_24_hours:
        return True
    if not current.is_closed and current.opens_at is not None and current.closes_at is not None:
        if current.opens_at < current.closes_at:
            if current.opens_at <= clock < current.closes_at:
                return True
        elif clock >= current.opens_at:
            return True

    return bool(
        not previous.is_closed
        and not previous.is_24_hours
        and previous.opens_at is not None
        and previous.closes_at is not None
        and previous.opens_at > previous.closes_at
        and clock < previous.closes_at
    )


def export_demand_simulation(
    *,
    stage2d_dir: Path,
    output_dir: Path,
    start_date: date,
    days: int = 7,
    seed: int = 20260822,
    policy: DemandSimulationPolicy | None = None,
    on_branch: Callable[[int, int, PharmacyBranch, int, int, int], None] | None = None,
) -> DemandSimulationResult:
    """Replay synthetic demand against Stage 2D inventory one branch at a time."""

    if days <= 0:
        raise ValueError("days must be positive")
    policy = policy or DemandSimulationPolicy()
    policy.validate()

    stage2d_dir = stage2d_dir.resolve()
    if not (stage2d_dir / "_SUCCESS").exists():
        raise ValueError("Stage 2D dataset is incomplete: _SUCCESS marker is missing")
    manifest_path = stage2d_dir / "inventory_manifest.json"
    if not manifest_path.exists():
        raise ValueError("Stage 2D inventory_manifest.json is missing")
    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if source_manifest.get("stage") != "2D":
        raise ValueError("input manifest is not a Stage 2D dataset")

    branch_count = int(source_manifest["branch_count"])
    source_seed = int(source_manifest["seed"])
    network = PharmacyNetworkGenerator(seed=source_seed).generate(branch_count)
    branch_by_id = {str(branch.branch_id): branch for branch in network.branches}

    inventory_parts = sorted((stage2d_dir / "inventory").glob("part-*.csv"))
    batch_parts = sorted((stage2d_dir / "batches").glob("part-*.csv"))
    if not inventory_parts or len(inventory_parts) != len(batch_parts):
        raise ValueError("Stage 2D inventory/batch partitions are missing or misaligned")

    output_dir = output_dir.resolve()
    _prepare_output_directories(output_dir)
    success_marker = output_dir / "_SUCCESS"
    result_manifest_path = output_dir / "demand_manifest.json"
    daily_kpi_path = output_dir / "daily_branch_kpis.csv"
    if success_marker.exists():
        success_marker.unlink()

    totals = Counter()
    daily_handle = daily_kpi_path.open("w", encoding="utf-8-sig", newline="")
    daily_writer = csv.DictWriter(
        daily_handle, fieldnames=list(DailyBranchKpiRow.__dataclass_fields__)
    )
    daily_writer.writeheader()

    processed_branches = 0
    try:
        for partition_index, (inventory_part, batch_part) in enumerate(
            zip(inventory_parts, batch_parts, strict=True), start=1
        ):
            output = _open_output_partition(output_dir, partition_index)
            try:
                inventory_groups = _group_csv_rows(inventory_part)
                batch_groups = _group_csv_rows(batch_part)
                for (inventory_branch_id, inventory_rows), (batch_branch_id, batch_rows) in zip(
                    inventory_groups, batch_groups, strict=True
                ):
                    if inventory_branch_id != batch_branch_id:
                        raise ValueError("inventory and batch branch order do not match")
                    branch = branch_by_id.get(inventory_branch_id)
                    if branch is None:
                        raise ValueError(
                            "Stage 2D branch "
                            f"{inventory_branch_id} cannot be reconstructed from manifest"
                        )
                    first_row = inventory_rows[0]
                    if first_row["branch_code"] != branch.branch_code:
                        raise ValueError(
                            "reconstructed branch identity does not match Stage 2D data"
                        )

                    state = _build_branch_state(
                        branch=branch,
                        inventory_rows=inventory_rows,
                        batch_rows=batch_rows,
                        start_date=start_date,
                    )
                    branch_totals = _simulate_branch(
                        state=state,
                        start_date=start_date,
                        days=days,
                        seed=seed,
                        policy=policy,
                        output=output,
                        daily_writer=daily_writer,
                    )
                    _write_ending_state(state=state, output=output)
                    totals.update(branch_totals)
                    processed_branches += 1
                    if on_branch is not None:
                        on_branch(
                            processed_branches,
                            branch_count,
                            branch,
                            branch_totals["demand_lines"],
                            branch_totals["fulfilled_units"],
                            branch_totals["lost_units"],
                        )
            finally:
                output.close()
    finally:
        daily_handle.close()

    if processed_branches != branch_count:
        raise ValueError(
            f"processed {processed_branches} branches but Stage 2D manifest declares {branch_count}"
        )

    requested = totals["requested_units"]
    fulfilled = totals["fulfilled_units"]
    result_manifest = {
        "stage": "2E",
        "source_stage": "2D",
        "simulation_engine": "synthetic_structured_unit_demand_v1",
        "seed": seed,
        "source_inventory_seed": source_seed,
        "start_date": start_date.isoformat(),
        "days": days,
        "branch_count": processed_branches,
        "partition_count": len(inventory_parts),
        "baskets": totals["baskets"],
        "demand_lines": totals["demand_lines"],
        "requested_units": requested,
        "fulfilled_units": fulfilled,
        "lost_units": totals["lost_units"],
        "unit_fulfillment_rate_pct": round(fulfilled / requested * 100, 2) if requested else 0.0,
        "fulfilled_lines": totals["fulfilled_lines"],
        "partial_lines": totals["partial_lines"],
        "stockout_lines": totals["stockout_lines"],
        "reorder_triggers": totals["reorder_triggers"],
        "monetary_values_generated": False,
        "pricing_status": "not_simulated",
        "mapping_status": source_manifest.get(
            "mapping_status", "synthetic_cross_market_mapping"
        ),
        "demand_truth_boundary": (
            "Demand patterns are synthetic simulation assumptions, not observed Egyptian "
            "patient/customer demand or sales measurements."
        ),
        "memory_contract": (
            "one branch inventory + batch state retained at a time; completed branch "
            "sales outputs and ending state are written then released"
        ),
        "policy": asdict(policy),
        "completion_marker": "_SUCCESS",
    }
    result_manifest_path.write_text(
        json.dumps(result_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    success_marker.write_text("complete\n", encoding="utf-8")

    return DemandSimulationResult(
        output_dir=output_dir,
        manifest_path=result_manifest_path,
        success_marker_path=success_marker,
        daily_kpi_path=daily_kpi_path,
        branch_count=processed_branches,
        simulated_days=days,
        baskets=totals["baskets"],
        demand_lines=totals["demand_lines"],
        requested_units=requested,
        fulfilled_units=fulfilled,
        lost_units=totals["lost_units"],
        reorder_triggers=totals["reorder_triggers"],
        partition_count=len(inventory_parts),
    )


def _simulate_branch(
    *,
    state: _BranchState,
    start_date: date,
    days: int,
    seed: int,
    policy: DemandSimulationPolicy,
    output: _OutputPartition,
    daily_writer: csv.DictWriter,
) -> Counter[str]:
    rng = random.Random(_branch_seed(seed=seed, branch_id=state.branch.branch_id))
    product_ids = tuple(state.inventory)
    popularity = _product_popularity_profiles(product_ids, policy.product_popularity_exponent)
    sampler_by_month: dict[int, _WeightedProductSampler] = {}
    totals: Counter[str] = Counter()

    for day_offset in range(days):
        local_date = start_date + timedelta(days=day_offset)
        daily = _DailyAccumulator()
        open_hours = [
            hour
            for hour in range(24)
            if branch_is_open(
                state.branch,
                datetime.combine(local_date, time(hour), tzinfo=_CAIRO),
            )
        ]
        if not open_hours:
            _write_daily_kpi(state.branch, local_date, daily, daily_writer)
            continue

        weekday_multiplier = _weekday_multiplier(local_date)
        expected_baskets = policy.daily_baskets(state.branch) * weekday_multiplier
        hour_weights = {hour: _hour_weight(hour) for hour in open_hours}
        weight_sum = sum(hour_weights.values())

        for hour in open_hours:
            hourly_lambda = expected_baskets * hour_weights[hour] / weight_sum
            basket_count = _sample_poisson(rng, hourly_lambda)
            for basket_index in range(basket_count):
                basket_id = uuid5(
                    _DEMAND_NAMESPACE,
                    f"seed={seed}|branch={state.branch.branch_id}|date={local_date}|"
                    f"hour={hour}|basket={basket_index}",
                )
                occurred_local = datetime.combine(
                    local_date,
                    time(hour, rng.randrange(60), rng.randrange(60)),
                    tzinfo=_CAIRO,
                )
                channel = _choose_channel(rng, state.branch)
                line_count = _choose_line_count(rng, policy.max_lines_per_basket)
                sampler = sampler_by_month.get(local_date.month)
                if sampler is None:
                    sampler = _build_product_sampler(
                        product_ids=product_ids,
                        popularity=popularity,
                        month=local_date.month,
                    )
                    sampler_by_month[local_date.month] = sampler
                selected = _choose_distinct_products(
                    rng=rng,
                    sampler=sampler,
                    count=min(line_count, len(product_ids)),
                )
                daily.baskets += 1
                totals["baskets"] += 1

                for line_index, product_id in enumerate(selected, start=1):
                    quantity = _choose_unit_quantity(rng, policy.max_units_per_line)
                    demand_id = uuid5(
                        _DEMAND_NAMESPACE,
                        f"{basket_id}|line={line_index}|product={product_id}",
                    )
                    request = DemandRequest(
                        demand_id=demand_id,
                        basket_id=basket_id,
                        branch_id=state.branch.branch_id,
                        product_id=product_id,
                        occurred_at=occurred_local,
                        channel=channel,
                        requested_quantity=quantity,
                    )
                    outcome, movement, reorder_triggered, usable_before = _fulfill_request(
                        state=state,
                        request=request,
                        as_of=local_date,
                    )
                    item = state.inventory[product_id]
                    before_on_hand = item.on_hand_quantity + outcome.fulfilled_quantity

                    output.demand_writer.writerow(
                        asdict(
                            DemandLineRow(
                                demand_id=str(request.demand_id),
                                basket_id=str(request.basket_id),
                                branch_id=str(request.branch_id),
                                branch_code=state.branch.branch_code,
                                governorate=state.branch.location.governorate,
                                branch_scale=state.branch.scale.value,
                                occurred_at=request.occurred_at.isoformat(),
                                local_date=local_date.isoformat(),
                                local_hour=hour,
                                channel=request.channel.value,
                                product_id=str(product_id),
                                display_name=state.product_names[product_id],
                                synthetic_seasonality_profile=popularity[product_id][1],
                                requested_quantity=quantity,
                                fulfilled_quantity=outcome.fulfilled_quantity,
                                lost_quantity=outcome.lost_quantity,
                                fulfillment_status=outcome.status.value,
                                on_hand_before=before_on_hand,
                                on_hand_after=item.on_hand_quantity,
                                usable_batch_units_before=usable_before,
                                reorder_triggered=reorder_triggered,
                                recommended_reorder_quantity=(
                                    item.recommended_reorder_quantity
                                    if item.reorder_required
                                    else 0
                                ),
                                pricing_status="not_simulated",
                                mapping_status="synthetic_cross_market_mapping",
                            )
                        )
                    )
                    for allocation in outcome.fefo_allocations:
                        output.allocation_writer.writerow(
                            asdict(
                                BatchAllocationRow(
                                    demand_id=str(request.demand_id),
                                    branch_id=str(request.branch_id),
                                    product_id=str(product_id),
                                    batch_id=str(allocation.batch_id),
                                    batch_number=allocation.batch_number,
                                    expires_on=allocation.expires_on.isoformat(),
                                    allocated_quantity=allocation.quantity,
                                )
                            )
                        )
                    if movement is not None:
                        output.movement_writer.writerow(
                            asdict(
                                StockMovementRow(
                                    movement_id=str(movement.movement_id),
                                    demand_id=str(request.demand_id),
                                    branch_id=str(request.branch_id),
                                    product_id=str(product_id),
                                    quantity_delta=movement.quantity_delta,
                                    on_hand_before=movement.on_hand_before,
                                    on_hand_after=movement.on_hand_after,
                                    inventory_version_after=movement.inventory_version_after,
                                    occurred_at=movement.occurred_at.isoformat(),
                                )
                            )
                        )
                    if reorder_triggered:
                        output.reorder_writer.writerow(
                            asdict(
                                ReorderTriggerRow(
                                    demand_id=str(request.demand_id),
                                    branch_id=str(request.branch_id),
                                    product_id=str(product_id),
                                    occurred_at=request.occurred_at.isoformat(),
                                    available_quantity=item.available_quantity,
                                    reorder_point=item.reorder_policy.reorder_point,
                                    target_stock_level=item.reorder_policy.target_stock_level,
                                    recommended_reorder_quantity=item.recommended_reorder_quantity,
                                    inventory_version=item.version,
                                )
                            )
                        )

                    daily.demand_lines += 1
                    daily.requested_units += quantity
                    daily.fulfilled_units += outcome.fulfilled_quantity
                    daily.lost_units += outcome.lost_quantity
                    totals["demand_lines"] += 1
                    totals["requested_units"] += quantity
                    totals["fulfilled_units"] += outcome.fulfilled_quantity
                    totals["lost_units"] += outcome.lost_quantity
                    if outcome.status is DemandFulfillmentStatus.FULFILLED:
                        daily.fulfilled_lines += 1
                        totals["fulfilled_lines"] += 1
                    elif outcome.status is DemandFulfillmentStatus.PARTIAL:
                        daily.partial_lines += 1
                        totals["partial_lines"] += 1
                    else:
                        daily.stockout_lines += 1
                        totals["stockout_lines"] += 1
                    if reorder_triggered:
                        daily.reorder_triggers += 1
                        totals["reorder_triggers"] += 1

        _write_daily_kpi(state.branch, local_date, daily, daily_writer)

    return totals


def _fulfill_request(
    *, state: _BranchState, request: DemandRequest, as_of: date
):
    inventory = state.inventory[request.product_id]
    batches = state.batches[request.product_id]
    usable_before = sum(
        batch.on_hand_quantity
        for batch in batches
        if batch.on_hand_quantity > 0 and not batch.is_expired(as_of=as_of)
    )
    fulfilled = min(
        request.requested_quantity,
        inventory.available_quantity,
        usable_before,
    )
    lost = request.requested_quantity - fulfilled

    allocations = ()
    movement = None
    reorder_triggered = False
    if fulfilled > 0:
        consumption = consume_fefo(batches=batches, quantity=fulfilled, as_of=as_of)
        state.batches[request.product_id] = consumption.updated_batches
        allocations = consumption.allocations
        transition = inventory.apply_sale(
            branch_id=request.branch_id,
            product_id=request.product_id,
            quantity=fulfilled,
            sale_id=request.demand_id,
            occurred_at=request.occurred_at,
        )
        state.inventory[request.product_id] = transition.after
        movement = transition.movement
        reorder_triggered = transition.reorder_triggered

    status = (
        DemandFulfillmentStatus.FULFILLED
        if fulfilled == request.requested_quantity
        else DemandFulfillmentStatus.STOCKOUT
        if fulfilled == 0
        else DemandFulfillmentStatus.PARTIAL
    )
    outcome = DemandOutcome(
        demand=request,
        fulfilled_quantity=fulfilled,
        lost_quantity=lost,
        status=status,
        fefo_allocations=allocations,
    )
    return outcome, movement, reorder_triggered, usable_before


def _build_branch_state(
    *,
    branch: PharmacyBranch,
    inventory_rows: list[dict[str, str]],
    batch_rows: list[dict[str, str]],
    start_date: date,
) -> _BranchState:
    initial_time = datetime.combine(start_date, time.min, tzinfo=_CAIRO).astimezone(UTC)
    inventory: dict[UUID, InventoryItem] = {}
    source_rows: dict[UUID, dict[str, str]] = {}
    product_names: dict[UUID, str] = {}
    for row in inventory_rows:
        product_id = UUID(row["product_id"])
        item = InventoryItem(
            inventory_item_id=UUID(row["inventory_item_id"]),
            branch_id=UUID(row["branch_id"]),
            product_id=product_id,
            on_hand_quantity=int(row["on_hand_quantity"]),
            reserved_quantity=int(row["reserved_quantity"]),
            reorder_policy=ReorderPolicy(
                reorder_point=int(row["reorder_point"]),
                target_stock_level=int(row["target_stock_level"]),
            ),
            version=int(row["inventory_version"]),
            updated_at=initial_time,
        )
        inventory[product_id] = item
        source_rows[product_id] = row
        product_names[product_id] = row["display_name"]

    batches_by_product: dict[UUID, list[InventoryBatch]] = defaultdict(list)
    for row in batch_rows:
        product_id = UUID(row["product_id"])
        batches_by_product[product_id].append(
            InventoryBatch(
                batch_id=UUID(row["batch_id"]),
                branch_id=UUID(row["branch_id"]),
                product_id=product_id,
                batch_number=row["batch_number"],
                received_on=date.fromisoformat(row["received_on"]),
                expires_on=date.fromisoformat(row["expires_on"]),
                on_hand_quantity=int(row["on_hand_quantity"]),
            )
        )

    if set(inventory) != set(batches_by_product):
        raise ValueError("every inventory product must have batch state before Stage 2E")
    for product_id, item in inventory.items():
        batch_total = sum(batch.on_hand_quantity for batch in batches_by_product[product_id])
        if batch_total != item.on_hand_quantity:
            raise ValueError("Stage 2D inventory and batch quantities do not reconcile")

    return _BranchState(
        branch=branch,
        inventory=inventory,
        inventory_source_rows=source_rows,
        batches={key: tuple(value) for key, value in batches_by_product.items()},
        product_names=product_names,
    )


def _write_ending_state(*, state: _BranchState, output: _OutputPartition) -> None:
    for product_id, item in state.inventory.items():
        source = dict(state.inventory_source_rows[product_id])
        source["on_hand_quantity"] = str(item.on_hand_quantity)
        source["reserved_quantity"] = str(item.reserved_quantity)
        source["inventory_version"] = str(item.version)
        output.ending_inventory_writer.writerow(source)
        for batch in state.batches[product_id]:
            output.ending_batch_writer.writerow(
                {
                    "batch_id": str(batch.batch_id),
                    "branch_id": str(batch.branch_id),
                    "product_id": str(batch.product_id),
                    "batch_number": batch.batch_number,
                    "received_on": batch.received_on.isoformat(),
                    "expires_on": batch.expires_on.isoformat(),
                    "on_hand_quantity": batch.on_hand_quantity,
                }
            )


def _write_daily_kpi(
    branch: PharmacyBranch,
    local_date: date,
    daily: _DailyAccumulator,
    writer: csv.DictWriter,
) -> None:
    writer.writerow(
        asdict(
            DailyBranchKpiRow(
                branch_id=str(branch.branch_id),
                branch_code=branch.branch_code,
                governorate=branch.location.governorate,
                branch_scale=branch.scale.value,
                local_date=local_date.isoformat(),
                baskets=daily.baskets,
                demand_lines=daily.demand_lines,
                requested_units=daily.requested_units,
                fulfilled_units=daily.fulfilled_units,
                lost_units=daily.lost_units,
                fulfilled_lines=daily.fulfilled_lines,
                partial_lines=daily.partial_lines,
                stockout_lines=daily.stockout_lines,
                reorder_triggers=daily.reorder_triggers,
                unit_fulfillment_rate_pct=(
                    round(daily.fulfilled_units / daily.requested_units * 100, 2)
                    if daily.requested_units
                    else 0.0
                ),
            )
        )
    )


def _prepare_output_directories(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "demand_lines",
        "batch_allocations",
        "stock_movements",
        "reorder_triggers",
        "ending_inventory",
        "ending_batches",
    ):
        directory = output_dir / name
        directory.mkdir(parents=True, exist_ok=True)
        for stale in directory.glob("part-*.csv"):
            stale.unlink()
    for stale_name in ("daily_branch_kpis.csv", "demand_manifest.json", "_SUCCESS"):
        stale = output_dir / stale_name
        if stale.exists():
            stale.unlink()


def _open_output_partition(output_dir: Path, partition_number: int) -> _OutputPartition:
    stack = ExitStack()

    def open_writer(directory: str, fields: list[str]) -> tuple[TextIO, csv.DictWriter]:
        handle = stack.enter_context(
            (output_dir / directory / f"part-{partition_number:05d}.csv").open(
                "w", encoding="utf-8-sig", newline=""
            )
        )
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        return handle, writer

    demand_handle, demand_writer = open_writer(
        "demand_lines", list(DemandLineRow.__dataclass_fields__)
    )
    allocation_handle, allocation_writer = open_writer(
        "batch_allocations", list(BatchAllocationRow.__dataclass_fields__)
    )
    movement_handle, movement_writer = open_writer(
        "stock_movements", list(StockMovementRow.__dataclass_fields__)
    )
    reorder_handle, reorder_writer = open_writer(
        "reorder_triggers", list(ReorderTriggerRow.__dataclass_fields__)
    )

    inventory_fields = [
        "inventory_item_id",
        "branch_id",
        "organization_id",
        "branch_code",
        "governorate",
        "branch_scale",
        "product_id",
        "display_name",
        "dosage_form",
        "ndc_product_code",
        "ndc_package_code",
        "source_market",
        "simulation_market",
        "mapping_status",
        "on_hand_quantity",
        "reserved_quantity",
        "reorder_point",
        "target_stock_level",
        "batch_count",
        "inventory_version",
    ]
    batch_fields = [
        "batch_id",
        "branch_id",
        "product_id",
        "batch_number",
        "received_on",
        "expires_on",
        "on_hand_quantity",
    ]
    ending_inventory_handle, ending_inventory_writer = open_writer(
        "ending_inventory", inventory_fields
    )
    ending_batch_handle, ending_batch_writer = open_writer("ending_batches", batch_fields)

    return _OutputPartition(
        stack=stack,
        demand_handle=demand_handle,
        allocation_handle=allocation_handle,
        movement_handle=movement_handle,
        reorder_handle=reorder_handle,
        ending_inventory_handle=ending_inventory_handle,
        ending_batch_handle=ending_batch_handle,
        demand_writer=demand_writer,
        allocation_writer=allocation_writer,
        movement_writer=movement_writer,
        reorder_writer=reorder_writer,
        ending_inventory_writer=ending_inventory_writer,
        ending_batch_writer=ending_batch_writer,
    )


def _group_csv_rows(path: Path) -> Iterator[tuple[str, list[dict[str, str]]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for branch_id, rows in groupby(reader, key=lambda row: row["branch_id"]):
            yield branch_id, list(rows)


def _product_popularity_profiles(
    product_ids: Iterable[UUID], exponent: float
) -> dict[UUID, tuple[float, str]]:
    ranked = sorted(product_ids, key=_stable_product_score)
    result: dict[UUID, tuple[float, str]] = {}
    for rank, product_id in enumerate(ranked, start=1):
        base_weight = 1.0 / math.pow(rank + 2, exponent)
        result[product_id] = (base_weight, _seasonality_profile(product_id))
    return result


def _build_product_sampler(
    *,
    product_ids: tuple[UUID, ...],
    popularity: dict[UUID, tuple[float, str]],
    month: int,
) -> _WeightedProductSampler:
    cumulative: list[float] = []
    running = 0.0
    for product_id in product_ids:
        base_weight, profile = popularity[product_id]
        running += base_weight * _seasonality_multiplier(profile, month)
        cumulative.append(running)
    if running <= 0:
        raise ValueError("product demand weights must sum to a positive value")
    return _WeightedProductSampler(
        population=product_ids,
        cumulative_weights=tuple(cumulative),
        total_weight=running,
    )


def _choose_distinct_products(
    *,
    rng: random.Random,
    sampler: _WeightedProductSampler,
    count: int,
) -> tuple[UUID, ...]:
    selected: list[UUID] = []
    selected_set: set[UUID] = set()
    attempts = 0
    while len(selected) < count and attempts < count * 20:
        candidate = sampler.choose(rng)
        if candidate not in selected_set:
            selected.append(candidate)
            selected_set.add(candidate)
        attempts += 1
    if len(selected) < count:
        for candidate in sampler.population:
            if candidate not in selected_set:
                selected.append(candidate)
                selected_set.add(candidate)
                if len(selected) == count:
                    break
    return tuple(selected)

def _stable_product_score(product_id: UUID) -> int:
    return int.from_bytes(hashlib.blake2b(product_id.bytes, digest_size=8).digest(), "big")


def _seasonality_profile(product_id: UUID) -> str:
    bucket = _stable_product_score(product_id) % 100
    if bucket < 52:
        return "synthetic_stable"
    if bucket < 70:
        return "synthetic_winter_peak"
    if bucket < 88:
        return "synthetic_summer_peak"
    return "synthetic_transition_peak"


def _seasonality_multiplier(profile: str, month: int) -> float:
    if profile == "synthetic_stable":
        return 1.0
    if profile == "synthetic_winter_peak":
        return 1.45 if month in {12, 1, 2} else 0.78 if month in {6, 7, 8} else 1.0
    if profile == "synthetic_summer_peak":
        return 1.38 if month in {6, 7, 8} else 0.82 if month in {12, 1, 2} else 1.0
    return 1.28 if month in {3, 4, 9, 10} else 0.92


def _weekday_multiplier(value: date) -> float:
    return {
        0: 0.96,
        1: 0.99,
        2: 1.01,
        3: 1.08,
        4: 0.86,
        5: 1.10,
        6: 1.00,
    }[value.weekday()]


def _hour_weight(hour: int) -> float:
    weights = (
        0.22,
        0.14,
        0.09,
        0.06,
        0.06,
        0.09,
        0.16,
        0.34,
        0.62,
        0.84,
        0.98,
        1.08,
        1.14,
        1.10,
        1.02,
        0.98,
        1.03,
        1.14,
        1.28,
        1.42,
        1.50,
        1.36,
        1.06,
        0.68,
    )
    return weights[hour]


def _choose_line_count(rng: random.Random, max_lines: int) -> int:
    population = tuple(range(1, max_lines + 1))
    base = (0.63, 0.25, 0.09, 0.03)
    weights = base[:max_lines]
    return rng.choices(population, weights=weights, k=1)[0]


def _choose_unit_quantity(rng: random.Random, max_units: int) -> int:
    population = tuple(range(1, max_units + 1))
    base = (0.74, 0.19, 0.06, 0.01)
    weights = base[:max_units]
    return rng.choices(population, weights=weights, k=1)[0]


def _choose_channel(rng: random.Random, branch: PharmacyBranch) -> SaleChannel:
    mapping = {
        ServiceMode.IN_STORE: (SaleChannel.IN_STORE, 0.70),
        ServiceMode.DELIVERY: (SaleChannel.DELIVERY, 0.20),
        ServiceMode.CLICK_AND_COLLECT: (SaleChannel.CLICK_AND_COLLECT, 0.08),
        ServiceMode.ONLINE_FULFILLMENT: (SaleChannel.ONLINE_FULFILLMENT, 0.12),
    }
    options = [
        mapping[mode]
        for mode in sorted(branch.operating_profile.service_modes, key=lambda item: item.value)
    ]
    channels, weights = zip(*options, strict=True)
    return rng.choices(channels, weights=weights, k=1)[0]


def _sample_poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    threshold = math.exp(-lam)
    product = 1.0
    k = 0
    while product > threshold:
        k += 1
        product *= rng.random()
    return k - 1


def _branch_seed(*, seed: int, branch_id: UUID) -> int:
    payload = f"{seed}|{branch_id}".encode()
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "big")
