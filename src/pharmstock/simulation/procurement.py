"""Stage 2F / 2F.1 synthetic procurement and replenishment engine.

The engine consumes the completed Stage 2E ending state.  It performs one
end-of-cycle procurement run, one branch at a time, so the already-completed
Stage 2E demand history is never rewritten retroactively.

Truth boundary:
- inventory quantities and state transitions are internally reconciled;
- supplier identities, supplier lead times and procurement assignments are
  synthetic simulator assumptions;
- no prices, costs, revenue or profit are generated.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from itertools import groupby
from pathlib import Path
from typing import TextIO
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from pharmstock.domain import InventoryBatch, InventoryItem, ReorderPolicy, StockMovement
from pharmstock.domain.procurement import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    SupplierProfile,
    SupplierType,
)
from pharmstock.simulation.geography import EGYPT_GOVERNORATES, EgyptRegion
from pharmstock.simulation.network import PharmacyNetworkGenerator
from pharmstock.simulation.suppliers import (
    SupplierNetworkPolicy,
    allocate_supplier_quantities,
    build_branch_supplier_panel,
    build_scaled_supplier_network,
)

_PROCUREMENT_NAMESPACE = UUID("5d68188d-6da4-4c7b-9ee1-4d41e7d0f65a")
_CAIRO = ZoneInfo("Africa/Cairo")
_GOVERNORATE_REGION = {item.name_en: item.region.value for item in EGYPT_GOVERNORATES}


@dataclass(frozen=True, slots=True)
class ProcurementSimulationPolicy:
    """Explicit synthetic assumptions for one procurement cycle."""

    national_supplier_count: int = 2
    regional_supplier_per_region: int = 1
    national_base_lead_days: int = 2
    regional_base_lead_days: int = 1
    max_lead_time_jitter_days: int = 2
    expiry_min_days: int = 270
    expiry_max_days: int = 900

    def validate(self) -> None:
        if self.national_supplier_count <= 0:
            raise ValueError("national_supplier_count must be positive")
        if self.regional_supplier_per_region <= 0:
            raise ValueError("regional_supplier_per_region must be positive")
        if self.national_base_lead_days <= 0 or self.regional_base_lead_days <= 0:
            raise ValueError("base lead times must be positive")
        if self.max_lead_time_jitter_days < 0:
            raise ValueError("max_lead_time_jitter_days cannot be negative")
        if self.expiry_min_days <= 0 or self.expiry_max_days <= self.expiry_min_days:
            raise ValueError("expiry day range is invalid")


@dataclass(frozen=True, slots=True)
class SupplierRow:
    supplier_id: str
    supplier_code: str
    display_name: str
    supplier_type: str
    market_code: str
    base_lead_time_days: int
    service_regions: str
    service_governorates: str
    catalog_coverage_pct: float
    expected_fill_rate_pct: float
    reliability_score_pct: float
    cycle_capacity_units: int
    cold_chain_supported: bool
    synthetic_record: bool


@dataclass(frozen=True, slots=True)
class SupplierUtilizationRow:
    supplier_id: str
    supplier_code: str
    supplier_type: str
    cycle_capacity_units: int
    ordered_units: int
    remaining_capacity_units: int
    capacity_utilization_pct: float
    purchase_orders: int
    purchase_order_lines: int
    branches_served: int
    used_in_cycle: bool


@dataclass(frozen=True, slots=True)
class BranchSupplierPanelRow:
    branch_id: str
    branch_code: str
    governorate: str
    panel_rank: int
    supplier_id: str
    supplier_code: str
    supplier_type: str
    base_lead_time_days: int
    catalog_coverage_pct: float
    expected_fill_rate_pct: float
    reliability_score_pct: float
    cycle_capacity_units: int


@dataclass(frozen=True, slots=True)
class PurchaseOrderRow:
    purchase_order_id: str
    procurement_cycle_id: str
    branch_id: str
    branch_code: str
    governorate: str
    supplier_id: str
    supplier_code: str
    ordered_at: str
    expected_delivery_on: str
    line_count: int
    ordered_units: int
    monetary_values_generated: bool
    supplier_assignment_status: str


@dataclass(frozen=True, slots=True)
class PurchaseOrderLineRow:
    purchase_order_id: str
    branch_id: str
    product_id: str
    display_name: str
    ordered_quantity: int
    on_hand_before_order: int
    reorder_point: int
    target_stock_level: int
    source_reorder_demand_id: str


@dataclass(frozen=True, slots=True)
class GoodsReceiptRow:
    receipt_id: str
    purchase_order_id: str
    branch_id: str
    supplier_id: str
    received_at: str
    line_count: int
    received_units: int


@dataclass(frozen=True, slots=True)
class GoodsReceiptLineRow:
    receipt_id: str
    purchase_order_id: str
    branch_id: str
    product_id: str
    received_quantity: int
    batch_id: str
    batch_number: str
    expires_on: str


@dataclass(frozen=True, slots=True)
class RestockMovementRow:
    movement_id: str
    receipt_id: str
    purchase_order_id: str
    branch_id: str
    product_id: str
    quantity_delta: int
    on_hand_before: int
    on_hand_after: int
    inventory_version_after: int
    occurred_at: str


@dataclass(frozen=True, slots=True)
class ProcurementBacklogRow:
    branch_id: str
    branch_code: str
    product_id: str
    display_name: str
    desired_quantity: int
    ordered_quantity: int
    deferred_quantity: int
    reason: str


@dataclass(frozen=True, slots=True)
class BranchProcurementKpiRow:
    branch_id: str
    branch_code: str
    governorate: str
    branch_scale: str
    storage_capacity_units: int
    ending_stage2e_units: int
    reorder_candidates: int
    supplier_panel_size: int
    active_supplier_count: int
    purchase_orders: int
    ordered_units: int
    received_units: int
    deferred_units: int
    final_units: int
    final_storage_utilization_pct: float


@dataclass(frozen=True, slots=True)
class ProcurementSimulationResult:
    output_dir: Path
    manifest_path: Path
    success_marker_path: Path
    supplier_master_path: Path
    supplier_utilization_path: Path
    branch_supplier_panel_path: Path
    branch_kpi_path: Path
    branch_count: int
    suppliers: int
    suppliers_used: int
    purchase_orders: int
    purchase_order_lines: int
    ordered_units: int
    received_units: int
    deferred_units: int
    restock_movements: int
    partition_count: int


@dataclass(slots=True)
class _BranchState:
    branch_id: UUID
    branch_code: str
    governorate: str
    branch_scale: str
    storage_capacity_units: int
    inventory: dict[UUID, InventoryItem]
    inventory_source_rows: dict[UUID, dict[str, str]]
    product_names: dict[UUID, str]
    batches: dict[UUID, list[InventoryBatch]]
    reorder_source_ids: dict[UUID, UUID]


@dataclass(slots=True)
class _OutputPartition:
    stack: ExitStack
    po_handle: TextIO
    po_line_handle: TextIO
    receipt_handle: TextIO
    receipt_line_handle: TextIO
    movement_handle: TextIO
    ending_inventory_handle: TextIO
    ending_batch_handle: TextIO
    po_writer: csv.DictWriter
    po_line_writer: csv.DictWriter
    receipt_writer: csv.DictWriter
    receipt_line_writer: csv.DictWriter
    movement_writer: csv.DictWriter
    ending_inventory_writer: csv.DictWriter
    ending_batch_writer: csv.DictWriter

    def close(self) -> None:
        self.stack.close()


def build_synthetic_suppliers(
    *, seed: int, policy: ProcurementSimulationPolicy | None = None
) -> tuple[SupplierProfile, ...]:
    """Create deterministic fictional supplier master data."""

    policy = policy or ProcurementSimulationPolicy()
    policy.validate()
    suppliers: list[SupplierProfile] = []

    all_regions = tuple(region.value for region in EgyptRegion)
    for index in range(1, policy.national_supplier_count + 1):
        code = f"SIM-SUP-NAT-{index:02d}"
        suppliers.append(
            SupplierProfile(
                supplier_id=uuid5(_PROCUREMENT_NAMESPACE, f"seed={seed}|supplier={code}"),
                supplier_code=code,
                display_name=f"Synthetic National Distributor {index:02d}",
                supplier_type=SupplierType.NATIONAL_DISTRIBUTOR,
                base_lead_time_days=policy.national_base_lead_days + (index - 1),
                service_regions=all_regions,
            )
        )

    for region in EgyptRegion:
        for index in range(1, policy.regional_supplier_per_region + 1):
            code = f"SIM-SUP-{region.name[:3]}-{index:02d}"
            suppliers.append(
                SupplierProfile(
                    supplier_id=uuid5(_PROCUREMENT_NAMESPACE, f"seed={seed}|supplier={code}"),
                    supplier_code=code,
                    display_name=(
                        f"Synthetic {region.value.replace('_', ' ').title()} Wholesaler {index:02d}"
                    ),
                    supplier_type=SupplierType.REGIONAL_WHOLESALER,
                    base_lead_time_days=policy.regional_base_lead_days,
                    service_regions=(region.value,),
                )
            )
    return tuple(suppliers)


def export_procurement_cycle(
    *,
    stage2e_dir: Path,
    output_dir: Path,
    seed: int = 20260822,
    policy: ProcurementSimulationPolicy | None = None,
    supplier_network_policy: SupplierNetworkPolicy | None = None,
    stage_label: str = "2F",
    on_branch: Callable[[int, int, str, int, int, int], None] | None = None,
) -> ProcurementSimulationResult:
    """Run one end-of-cycle replenishment pass over completed Stage 2E output."""

    policy = policy or ProcurementSimulationPolicy()
    policy.validate()
    stage2e_dir = stage2e_dir.resolve()
    if not (stage2e_dir / "_SUCCESS").exists():
        raise ValueError("Stage 2E dataset is incomplete: _SUCCESS marker is missing")
    source_manifest_path = stage2e_dir / "demand_manifest.json"
    if not source_manifest_path.exists():
        raise ValueError("Stage 2E demand_manifest.json is missing")
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    if source_manifest.get("stage") != "2E":
        raise ValueError("input manifest is not a Stage 2E dataset")

    branch_count = int(source_manifest["branch_count"])
    source_inventory_seed = int(source_manifest["source_inventory_seed"])
    partition_count = int(source_manifest["partition_count"])
    network = PharmacyNetworkGenerator(seed=source_inventory_seed).generate(branch_count)
    branch_by_id = {str(branch.branch_id): branch for branch in network.branches}

    if supplier_network_policy is None:
        suppliers = build_synthetic_suppliers(seed=seed, policy=policy)
        preferred_panel_size: int | None = None
        supplier_network_mode = "legacy_six_supplier_checkpoint"
    else:
        supplier_network_policy.validate()
        suppliers = build_scaled_supplier_network(seed=seed, policy=supplier_network_policy)
        preferred_panel_size = supplier_network_policy.preferred_supplier_panel_size
        supplier_network_mode = "scaled_supplier_ecosystem_v1"
    supplier_by_id = {supplier.supplier_id: supplier for supplier in suppliers}
    supplier_capacity_remaining = {
        supplier.supplier_id: supplier.cycle_capacity_units for supplier in suppliers
    }
    supplier_usage: dict[UUID, Counter[str]] = defaultdict(Counter)
    supplier_branches: dict[UUID, set[UUID]] = defaultdict(set)
    cycle_token = (
        f"seed={seed}|stage2e={source_manifest.get('start_date')}|"
        f"days={source_manifest.get('days')}"
    )
    procurement_cycle_id = uuid5(_PROCUREMENT_NAMESPACE, cycle_token)
    cycle_start = _procurement_cycle_start(source_manifest)

    inventory_parts = sorted((stage2e_dir / "ending_inventory").glob("part-*.csv"))
    batch_parts = sorted((stage2e_dir / "ending_batches").glob("part-*.csv"))
    reorder_parts = sorted((stage2e_dir / "reorder_triggers").glob("part-*.csv"))
    if not inventory_parts or len(inventory_parts) != len(batch_parts):
        raise ValueError("Stage 2E ending inventory/batch partitions are missing or misaligned")
    if len(inventory_parts) != partition_count:
        raise ValueError("Stage 2E partition count does not match manifest")

    reorder_source_ids = _load_reorder_source_ids(reorder_parts)
    output_dir = output_dir.resolve()
    _prepare_output_directories(output_dir)
    supplier_master_path = output_dir / "supplier_master.csv"
    supplier_utilization_path = output_dir / "supplier_utilization.csv"
    branch_supplier_panel_path = output_dir / "branch_supplier_panels.csv"
    branch_kpi_path = output_dir / "branch_procurement_kpis.csv"
    manifest_path = output_dir / "procurement_manifest.json"
    success_marker = output_dir / "_SUCCESS"
    _write_supplier_master(supplier_master_path, suppliers)

    totals: Counter[str] = Counter()
    processed = 0
    kpi_handle = branch_kpi_path.open("w", encoding="utf-8-sig", newline="")
    kpi_writer = csv.DictWriter(
        kpi_handle, fieldnames=list(BranchProcurementKpiRow.__dataclass_fields__)
    )
    kpi_writer.writeheader()
    panel_handle = branch_supplier_panel_path.open("w", encoding="utf-8-sig", newline="")
    panel_writer = csv.DictWriter(
        panel_handle, fieldnames=list(BranchSupplierPanelRow.__dataclass_fields__)
    )
    panel_writer.writeheader()
    backlog_handle = (output_dir / "procurement_backlog.csv").open(
        "w", encoding="utf-8-sig", newline=""
    )
    backlog_writer = csv.DictWriter(
        backlog_handle, fieldnames=list(ProcurementBacklogRow.__dataclass_fields__)
    )
    backlog_writer.writeheader()

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
                        raise ValueError(
                            "Stage 2E inventory and batch branch ordering does not match"
                        )
                    branch = branch_by_id.get(inventory_branch_id)
                    if branch is None:
                        raise ValueError(f"cannot reconstruct branch {inventory_branch_id}")
                    state = _build_branch_state(
                        branch=branch,
                        inventory_rows=inventory_rows,
                        batch_rows=batch_rows,
                        reorder_source_ids=reorder_source_ids.get(inventory_branch_id, {}),
                    )
                    branch_totals = _replenish_branch(
                        state=state,
                        suppliers=suppliers,
                        supplier_by_id=supplier_by_id,
                        supplier_capacity_remaining=supplier_capacity_remaining,
                        supplier_usage=supplier_usage,
                        supplier_branches=supplier_branches,
                        preferred_panel_size=preferred_panel_size,
                        procurement_cycle_id=procurement_cycle_id,
                        cycle_start=cycle_start,
                        seed=seed,
                        policy=policy,
                        output=output,
                        backlog_writer=backlog_writer,
                        panel_writer=panel_writer,
                        kpi_writer=kpi_writer,
                    )
                    totals.update(branch_totals)
                    processed += 1
                    if on_branch is not None:
                        on_branch(
                            processed,
                            branch_count,
                            branch.branch_code,
                            branch_totals["purchase_orders"],
                            branch_totals["received_units"],
                            branch_totals["deferred_units"],
                        )
            finally:
                output.close()
    finally:
        kpi_handle.close()
        panel_handle.close()
        backlog_handle.close()

    _write_supplier_utilization(
        supplier_utilization_path,
        suppliers=suppliers,
        capacity_remaining=supplier_capacity_remaining,
        usage=supplier_usage,
        branches=supplier_branches,
    )

    if processed != branch_count:
        raise ValueError(f"processed {processed} branches but manifest declares {branch_count}")
    if totals["ordered_units"] != totals["received_units"]:
        raise AssertionError(
            "Stage 2F default supplier policy requires ordered units == received units"
        )
    if totals["restock_delta"] != totals["received_units"]:
        raise AssertionError("restock movement delta must equal received units")

    result_manifest = {
        "stage": stage_label,
        "source_stage": "2E",
        "procurement_engine": (
            "synthetic_end_of_cycle_replenishment_supplier_network_v2"
            if supplier_network_policy is not None
            else "synthetic_end_of_cycle_replenishment_v1"
        ),
        "supplier_network_mode": supplier_network_mode,
        "seed": seed,
        "procurement_cycle_id": str(procurement_cycle_id),
        "cycle_start": cycle_start.isoformat(),
        "branch_count": processed,
        "partition_count": len(inventory_parts),
        "supplier_count": len(suppliers),
        "suppliers_used": sum(
            1
            for supplier in suppliers
            if supplier_usage[supplier.supplier_id]["purchase_orders"] > 0
        ),
        "supplier_type_counts": dict(
            Counter(supplier.supplier_type.value for supplier in suppliers)
        ),
        "supplier_network_policy": (
            asdict(supplier_network_policy) if supplier_network_policy else None
        ),
        "purchase_orders": totals["purchase_orders"],
        "purchase_order_lines": totals["purchase_order_lines"],
        "ordered_units": totals["ordered_units"],
        "goods_receipts": totals["goods_receipts"],
        "received_units": totals["received_units"],
        "deferred_units": totals["deferred_units"],
        "restock_movements": totals["restock_movements"],
        "monetary_values_generated": False,
        "pricing_status": "not_simulated",
        "supplier_truth_boundary": (
            "Supplier identities, geographic coverage, catalog coverage, capacity, reliability, "
            "fill-rate expectations and lead times are synthetic simulator assumptions; they are "
            "not records of real Egyptian pharmaceutical distributors."
        ),
        "capacity_rule": (
            "restock allocations cannot raise a branch's physical on-hand units above its "
            "storage_capacity_units"
        ),
        "timing_rule": (
            "procurement starts after the completed Stage 2E demand window; Stage 2E historical "
            "sales are never retroactively rewritten"
        ),
        "memory_contract": "one branch ending state retained at a time, written, then released",
        "policy": asdict(policy),
        "completion_marker": "_SUCCESS",
    }
    manifest_path.write_text(
        json.dumps(result_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    success_marker.write_text("complete\n", encoding="utf-8")

    return ProcurementSimulationResult(
        output_dir=output_dir,
        manifest_path=manifest_path,
        success_marker_path=success_marker,
        supplier_master_path=supplier_master_path,
        supplier_utilization_path=supplier_utilization_path,
        branch_supplier_panel_path=branch_supplier_panel_path,
        branch_kpi_path=branch_kpi_path,
        branch_count=processed,
        suppliers=len(suppliers),
        suppliers_used=sum(
            1
            for supplier in suppliers
            if supplier_usage[supplier.supplier_id]["purchase_orders"] > 0
        ),
        purchase_orders=totals["purchase_orders"],
        purchase_order_lines=totals["purchase_order_lines"],
        ordered_units=totals["ordered_units"],
        received_units=totals["received_units"],
        deferred_units=totals["deferred_units"],
        restock_movements=totals["restock_movements"],
        partition_count=len(inventory_parts),
    )


def _replenish_branch(
    *,
    state: _BranchState,
    suppliers: tuple[SupplierProfile, ...],
    supplier_by_id: dict[UUID, SupplierProfile],
    supplier_capacity_remaining: dict[UUID, int],
    supplier_usage: dict[UUID, Counter[str]],
    supplier_branches: dict[UUID, set[UUID]],
    preferred_panel_size: int | None,
    procurement_cycle_id: UUID,
    cycle_start: datetime,
    seed: int,
    policy: ProcurementSimulationPolicy,
    output: _OutputPartition,
    backlog_writer: csv.DictWriter,
    panel_writer: csv.DictWriter,
    kpi_writer: csv.DictWriter,
) -> Counter[str]:
    totals: Counter[str] = Counter()
    initial_units = sum(item.on_hand_quantity for item in state.inventory.values())
    remaining_capacity = max(state.storage_capacity_units - initial_units, 0)
    candidates = [
        item
        for item in state.inventory.values()
        if item.reorder_required and item.recommended_reorder_quantity > 0
    ]
    candidates.sort(
        key=lambda item: (
            item.available_quantity / max(item.reorder_policy.target_stock_level, 1),
            str(item.product_id),
        )
    )

    if preferred_panel_size is None:
        preferred_panel = suppliers
    else:
        preferred_panel = build_branch_supplier_panel(
            suppliers=suppliers,
            branch_id=state.branch_id,
            governorate=state.governorate,
            panel_size=preferred_panel_size,
        )

    for rank, supplier in enumerate(preferred_panel, start=1):
        panel_writer.writerow(
            asdict(
                BranchSupplierPanelRow(
                    branch_id=str(state.branch_id),
                    branch_code=state.branch_code,
                    governorate=state.governorate,
                    panel_rank=rank,
                    supplier_id=str(supplier.supplier_id),
                    supplier_code=supplier.supplier_code,
                    supplier_type=supplier.supplier_type.value,
                    base_lead_time_days=supplier.base_lead_time_days,
                    catalog_coverage_pct=round(supplier.catalog_coverage_ratio * 100, 2),
                    expected_fill_rate_pct=round(supplier.expected_fill_rate * 100, 2),
                    reliability_score_pct=round(supplier.reliability_score * 100, 2),
                    cycle_capacity_units=supplier.cycle_capacity_units,
                )
            )
        )

    grouped: dict[UUID, list[PurchaseOrderLine]] = defaultdict(list)
    backlog_rows: list[ProcurementBacklogRow] = []
    for item in candidates:
        desired = item.recommended_reorder_quantity
        branch_allowed = min(desired, remaining_capacity)
        storage_deferred = desired - branch_allowed
        ordered = 0

        if branch_allowed > 0 and preferred_panel_size is None:
            supplier = _assign_supplier_legacy(
                suppliers=suppliers,
                governorate=state.governorate,
                product_id=item.product_id,
            )
            grouped[supplier.supplier_id].append(
                PurchaseOrderLine(
                    product_id=item.product_id,
                    ordered_quantity=branch_allowed,
                    source_reorder_demand_id=state.reorder_source_ids.get(item.product_id),
                )
            )
            supplier_capacity_remaining[supplier.supplier_id] -= branch_allowed
            ordered = branch_allowed
            supplier_deferred = 0
            remaining_capacity -= ordered
        elif branch_allowed > 0:
            allocations, supplier_deferred = allocate_supplier_quantities(
                suppliers=suppliers,
                preferred_panel=preferred_panel,
                governorate=state.governorate,
                product_id=item.product_id,
                required_quantity=branch_allowed,
                capacity_remaining=supplier_capacity_remaining,
            )
            for allocation in allocations:
                grouped[allocation.supplier.supplier_id].append(
                    PurchaseOrderLine(
                        product_id=item.product_id,
                        ordered_quantity=allocation.quantity,
                        source_reorder_demand_id=state.reorder_source_ids.get(item.product_id),
                    )
                )
                ordered += allocation.quantity
            remaining_capacity -= ordered
        else:
            supplier_deferred = 0

        if storage_deferred > 0:
            backlog_rows.append(
                ProcurementBacklogRow(
                    branch_id=str(state.branch_id),
                    branch_code=state.branch_code,
                    product_id=str(item.product_id),
                    display_name=state.product_names[item.product_id],
                    desired_quantity=desired,
                    ordered_quantity=ordered,
                    deferred_quantity=storage_deferred,
                    reason="storage_capacity_limit",
                )
            )
            totals["deferred_units"] += storage_deferred

        if supplier_deferred > 0:
            backlog_rows.append(
                ProcurementBacklogRow(
                    branch_id=str(state.branch_id),
                    branch_code=state.branch_code,
                    product_id=str(item.product_id),
                    display_name=state.product_names[item.product_id],
                    desired_quantity=branch_allowed,
                    ordered_quantity=ordered,
                    deferred_quantity=supplier_deferred,
                    reason="supplier_assortment_or_cycle_capacity_limit",
                )
            )
            totals["deferred_units"] += supplier_deferred

    for backlog in backlog_rows:
        backlog_writer.writerow(asdict(backlog))

    for supplier_id, lines in sorted(grouped.items(), key=lambda item: str(item[0])):
        supplier = supplier_by_id[supplier_id]
        lead_days = _lead_time_days(
            seed=seed,
            branch_id=state.branch_id,
            supplier=supplier,
            policy=policy,
        )
        expected_delivery_on = cycle_start.date() + timedelta(days=lead_days)
        po_id = uuid5(
            _PROCUREMENT_NAMESPACE,
            f"cycle={procurement_cycle_id}|branch={state.branch_id}|supplier={supplier_id}",
        )
        po = PurchaseOrder(
            purchase_order_id=po_id,
            branch_id=state.branch_id,
            supplier_id=supplier_id,
            ordered_at=cycle_start,
            expected_delivery_on=expected_delivery_on,
            line_items=tuple(lines),
            procurement_cycle_id=procurement_cycle_id,
        )
        output.po_writer.writerow(
            asdict(
                PurchaseOrderRow(
                    purchase_order_id=str(po.purchase_order_id),
                    procurement_cycle_id=str(procurement_cycle_id),
                    branch_id=str(state.branch_id),
                    branch_code=state.branch_code,
                    governorate=state.governorate,
                    supplier_id=str(supplier.supplier_id),
                    supplier_code=supplier.supplier_code,
                    ordered_at=po.ordered_at.isoformat(),
                    expected_delivery_on=po.expected_delivery_on.isoformat(),
                    line_count=len(po.line_items),
                    ordered_units=po.total_ordered_quantity,
                    monetary_values_generated=False,
                    supplier_assignment_status=(
                        "synthetic_ranked_panel"
                        if preferred_panel_size is not None
                        else "synthetic_legacy"
                    ),
                )
            )
        )
        totals["purchase_orders"] += 1
        totals["ordered_units"] += po.total_ordered_quantity
        supplier_usage[supplier_id]["purchase_orders"] += 1
        supplier_usage[supplier_id]["ordered_units"] += po.total_ordered_quantity
        supplier_branches[supplier_id].add(state.branch_id)
        for line in po.line_items:
            item = state.inventory[line.product_id]
            output.po_line_writer.writerow(
                asdict(
                    PurchaseOrderLineRow(
                        purchase_order_id=str(po.purchase_order_id),
                        branch_id=str(state.branch_id),
                        product_id=str(line.product_id),
                        display_name=state.product_names[line.product_id],
                        ordered_quantity=line.ordered_quantity,
                        on_hand_before_order=item.on_hand_quantity,
                        reorder_point=item.reorder_policy.reorder_point,
                        target_stock_level=item.reorder_policy.target_stock_level,
                        source_reorder_demand_id=(
                            str(line.source_reorder_demand_id)
                            if line.source_reorder_demand_id is not None
                            else ""
                        ),
                    )
                )
            )
            totals["purchase_order_lines"] += 1
            supplier_usage[supplier_id]["purchase_order_lines"] += 1

        received_at = datetime.combine(
            expected_delivery_on,
            time(10, 0),
            tzinfo=_CAIRO,
        ).astimezone(UTC)
        receipt_id = uuid5(_PROCUREMENT_NAMESPACE, f"po={po.purchase_order_id}|receipt=1")
        receipt_lines: list[GoodsReceiptLine] = []
        new_batches: list[tuple[UUID, InventoryBatch]] = []
        for line_number, line in enumerate(po.line_items, start=1):
            expiry_days = _expiry_days(
                seed=seed,
                product_id=line.product_id,
                receipt_id=receipt_id,
                policy=policy,
            )
            batch_number = (
                f"PROC-{supplier.supplier_code}-{str(po.purchase_order_id)[:8].upper()}-"
                f"{line_number:04d}"
            )
            expires_on = expected_delivery_on + timedelta(days=expiry_days)
            receipt_lines.append(
                GoodsReceiptLine(
                    product_id=line.product_id,
                    received_quantity=line.ordered_quantity,
                    batch_number=batch_number,
                    expires_on=expires_on,
                )
            )
            batch = InventoryBatch(
                batch_id=uuid5(
                    _PROCUREMENT_NAMESPACE,
                    f"receipt={receipt_id}|product={line.product_id}|batch={batch_number}",
                ),
                branch_id=state.branch_id,
                product_id=line.product_id,
                batch_number=batch_number,
                received_on=expected_delivery_on,
                expires_on=expires_on,
                on_hand_quantity=line.ordered_quantity,
            )
            new_batches.append((line.product_id, batch))

        receipt = GoodsReceipt(
            receipt_id=receipt_id,
            purchase_order_id=po.purchase_order_id,
            branch_id=state.branch_id,
            supplier_id=supplier_id,
            received_at=received_at,
            line_items=tuple(receipt_lines),
        )
        output.receipt_writer.writerow(
            asdict(
                GoodsReceiptRow(
                    receipt_id=str(receipt.receipt_id),
                    purchase_order_id=str(po.purchase_order_id),
                    branch_id=str(state.branch_id),
                    supplier_id=str(supplier_id),
                    received_at=receipt.received_at.isoformat(),
                    line_count=len(receipt.line_items),
                    received_units=receipt.total_received_quantity,
                )
            )
        )
        totals["goods_receipts"] += 1
        totals["received_units"] += receipt.total_received_quantity
        supplier_usage[supplier_id]["received_units"] += receipt.total_received_quantity

        batch_by_product = {product_id: batch for product_id, batch in new_batches}
        for line in receipt.line_items:
            batch = batch_by_product[line.product_id]
            output.receipt_line_writer.writerow(
                asdict(
                    GoodsReceiptLineRow(
                        receipt_id=str(receipt.receipt_id),
                        purchase_order_id=str(po.purchase_order_id),
                        branch_id=str(state.branch_id),
                        product_id=str(line.product_id),
                        received_quantity=line.received_quantity,
                        batch_id=str(batch.batch_id),
                        batch_number=batch.batch_number,
                        expires_on=batch.expires_on.isoformat(),
                    )
                )
            )
            item = state.inventory[line.product_id]
            transition = item.apply_restock(
                branch_id=state.branch_id,
                product_id=line.product_id,
                quantity=line.received_quantity,
                restock_id=receipt.receipt_id,
                occurred_at=receipt.received_at,
            )
            movement = transition.movement.model_copy(
                update={
                    "movement_id": uuid5(
                        _PROCUREMENT_NAMESPACE,
                        f"receipt={receipt.receipt_id}|product={line.product_id}|movement",
                    )
                }
            )
            state.inventory[line.product_id] = transition.after
            state.batches[line.product_id].append(batch)
            _write_restock_movement(
                output=output,
                movement=movement,
                receipt_id=receipt.receipt_id,
                purchase_order_id=po.purchase_order_id,
            )
            totals["restock_movements"] += 1
            totals["restock_delta"] += movement.quantity_delta

    _write_ending_state(state=state, output=output)
    final_units = sum(item.on_hand_quantity for item in state.inventory.values())
    if final_units > state.storage_capacity_units:
        raise AssertionError("procurement restock exceeded branch storage capacity")
    if final_units != initial_units + totals["received_units"]:
        raise AssertionError("branch final inventory does not reconcile with received units")

    totals["reorder_candidates"] = len(candidates)
    totals["initial_units"] = initial_units
    totals["final_units"] = final_units
    kpi_writer.writerow(
        asdict(
            BranchProcurementKpiRow(
                branch_id=str(state.branch_id),
                branch_code=state.branch_code,
                governorate=state.governorate,
                branch_scale=state.branch_scale,
                storage_capacity_units=state.storage_capacity_units,
                ending_stage2e_units=initial_units,
                reorder_candidates=len(candidates),
                supplier_panel_size=len(preferred_panel),
                active_supplier_count=len(grouped),
                purchase_orders=totals["purchase_orders"],
                ordered_units=totals["ordered_units"],
                received_units=totals["received_units"],
                deferred_units=totals["deferred_units"],
                final_units=final_units,
                final_storage_utilization_pct=round(
                    final_units / state.storage_capacity_units * 100, 2
                ),
            )
        )
    )
    return totals


def _build_branch_state(
    *,
    branch,
    inventory_rows: list[dict[str, str]],
    batch_rows: list[dict[str, str]],
    reorder_source_ids: dict[UUID, UUID],
) -> _BranchState:
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
            updated_at=datetime.now(UTC),
        )
        inventory[product_id] = item
        source_rows[product_id] = dict(row)
        product_names[product_id] = row["display_name"]

    batches: dict[UUID, list[InventoryBatch]] = defaultdict(list)
    for row in batch_rows:
        product_id = UUID(row["product_id"])
        batches[product_id].append(
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
    for product_id in inventory:
        batches.setdefault(product_id, [])

    return _BranchState(
        branch_id=branch.branch_id,
        branch_code=branch.branch_code,
        governorate=branch.location.governorate,
        branch_scale=branch.scale.value,
        storage_capacity_units=branch.capacity.storage_capacity_units,
        inventory=inventory,
        inventory_source_rows=source_rows,
        product_names=product_names,
        batches=batches,
        reorder_source_ids=reorder_source_ids,
    )


def _write_ending_state(*, state: _BranchState, output: _OutputPartition) -> None:
    for product_id, item in state.inventory.items():
        source = dict(state.inventory_source_rows[product_id])
        source["on_hand_quantity"] = str(item.on_hand_quantity)
        source["reserved_quantity"] = str(item.reserved_quantity)
        active_batch_count = sum(
            1 for batch in state.batches[product_id] if batch.on_hand_quantity > 0
        )
        source["batch_count"] = str(active_batch_count)
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


def _write_restock_movement(
    *, output: _OutputPartition, movement: StockMovement, receipt_id: UUID, purchase_order_id: UUID
) -> None:
    output.movement_writer.writerow(
        asdict(
            RestockMovementRow(
                movement_id=str(movement.movement_id),
                receipt_id=str(receipt_id),
                purchase_order_id=str(purchase_order_id),
                branch_id=str(movement.branch_id),
                product_id=str(movement.product_id),
                quantity_delta=movement.quantity_delta,
                on_hand_before=movement.on_hand_before,
                on_hand_after=movement.on_hand_after,
                inventory_version_after=movement.inventory_version_after,
                occurred_at=movement.occurred_at.isoformat(),
            )
        )
    )


def _assign_supplier_legacy(
    *, suppliers: tuple[SupplierProfile, ...], governorate: str, product_id: UUID
) -> SupplierProfile:
    region = _GOVERNORATE_REGION[governorate]
    eligible = [supplier for supplier in suppliers if region in supplier.service_regions]
    if not eligible:
        raise ValueError(f"no synthetic supplier serves region {region}")
    score = int.from_bytes(hashlib.sha256(product_id.bytes).digest()[:8], "big")
    return eligible[score % len(eligible)]


def _lead_time_days(
    *, seed: int, branch_id: UUID, supplier: SupplierProfile, policy: ProcurementSimulationPolicy
) -> int:
    token = f"seed={seed}|branch={branch_id}|supplier={supplier.supplier_id}".encode()
    jitter = int.from_bytes(hashlib.sha256(token).digest()[:2], "big") % (
        policy.max_lead_time_jitter_days + 1
    )
    return supplier.base_lead_time_days + jitter


def _expiry_days(
    *, seed: int, product_id: UUID, receipt_id: UUID, policy: ProcurementSimulationPolicy
) -> int:
    token = f"seed={seed}|product={product_id}|receipt={receipt_id}".encode()
    span = policy.expiry_max_days - policy.expiry_min_days + 1
    return policy.expiry_min_days + int.from_bytes(hashlib.sha256(token).digest()[:4], "big") % span


def _procurement_cycle_start(source_manifest: dict[str, object]) -> datetime:
    start = date.fromisoformat(str(source_manifest["start_date"]))
    days = int(source_manifest["days"])
    local_date = start + timedelta(days=days)
    return datetime.combine(local_date, time(8, 0), tzinfo=_CAIRO).astimezone(UTC)


def _load_reorder_source_ids(paths: list[Path]) -> dict[str, dict[UUID, UUID]]:
    result: dict[str, dict[UUID, UUID]] = defaultdict(dict)
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                branch_id = row["branch_id"]
                product_id = UUID(row["product_id"])
                result[branch_id].setdefault(product_id, UUID(row["demand_id"]))
    return result


def _write_supplier_master(path: Path, suppliers: tuple[SupplierProfile, ...]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SupplierRow.__dataclass_fields__))
        writer.writeheader()
        for supplier in suppliers:
            writer.writerow(
                asdict(
                    SupplierRow(
                        supplier_id=str(supplier.supplier_id),
                        supplier_code=supplier.supplier_code,
                        display_name=supplier.display_name,
                        supplier_type=supplier.supplier_type.value,
                        market_code=supplier.market_code,
                        base_lead_time_days=supplier.base_lead_time_days,
                        service_regions="|".join(supplier.service_regions),
                        service_governorates="|".join(supplier.service_governorates),
                        catalog_coverage_pct=round(supplier.catalog_coverage_ratio * 100, 2),
                        expected_fill_rate_pct=round(supplier.expected_fill_rate * 100, 2),
                        reliability_score_pct=round(supplier.reliability_score * 100, 2),
                        cycle_capacity_units=supplier.cycle_capacity_units,
                        cold_chain_supported=supplier.cold_chain_supported,
                        synthetic_record=supplier.synthetic_record,
                    )
                )
            )


def _write_supplier_utilization(
    path: Path,
    *,
    suppliers: tuple[SupplierProfile, ...],
    capacity_remaining: dict[UUID, int],
    usage: dict[UUID, Counter[str]],
    branches: dict[UUID, set[UUID]],
) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(SupplierUtilizationRow.__dataclass_fields__)
        )
        writer.writeheader()
        for supplier in suppliers:
            supplier_usage = usage[supplier.supplier_id]
            remaining = capacity_remaining[supplier.supplier_id]
            ordered = supplier_usage["ordered_units"]
            writer.writerow(
                asdict(
                    SupplierUtilizationRow(
                        supplier_id=str(supplier.supplier_id),
                        supplier_code=supplier.supplier_code,
                        supplier_type=supplier.supplier_type.value,
                        cycle_capacity_units=supplier.cycle_capacity_units,
                        ordered_units=ordered,
                        remaining_capacity_units=remaining,
                        capacity_utilization_pct=round(
                            ordered / supplier.cycle_capacity_units * 100, 4
                        ),
                        purchase_orders=supplier_usage["purchase_orders"],
                        purchase_order_lines=supplier_usage["purchase_order_lines"],
                        branches_served=len(branches[supplier.supplier_id]),
                        used_in_cycle=supplier_usage["purchase_orders"] > 0,
                    )
                )
            )


def _prepare_output_directories(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "purchase_orders",
        "purchase_order_lines",
        "goods_receipts",
        "goods_receipt_lines",
        "restock_movements",
        "ending_inventory",
        "ending_batches",
    ):
        directory = output_dir / name
        directory.mkdir(parents=True, exist_ok=True)
        for stale in directory.glob("part-*.csv"):
            stale.unlink()
    for stale_name in (
        "supplier_master.csv",
        "supplier_utilization.csv",
        "branch_supplier_panels.csv",
        "branch_procurement_kpis.csv",
        "procurement_backlog.csv",
        "procurement_manifest.json",
        "_SUCCESS",
    ):
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

    po_handle, po_writer = open_writer(
        "purchase_orders", list(PurchaseOrderRow.__dataclass_fields__)
    )
    po_line_handle, po_line_writer = open_writer(
        "purchase_order_lines", list(PurchaseOrderLineRow.__dataclass_fields__)
    )
    receipt_handle, receipt_writer = open_writer(
        "goods_receipts", list(GoodsReceiptRow.__dataclass_fields__)
    )
    receipt_line_handle, receipt_line_writer = open_writer(
        "goods_receipt_lines", list(GoodsReceiptLineRow.__dataclass_fields__)
    )
    movement_handle, movement_writer = open_writer(
        "restock_movements", list(RestockMovementRow.__dataclass_fields__)
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
        po_handle=po_handle,
        po_line_handle=po_line_handle,
        receipt_handle=receipt_handle,
        receipt_line_handle=receipt_line_handle,
        movement_handle=movement_handle,
        ending_inventory_handle=ending_inventory_handle,
        ending_batch_handle=ending_batch_handle,
        po_writer=po_writer,
        po_line_writer=po_line_writer,
        receipt_writer=receipt_writer,
        receipt_line_writer=receipt_line_writer,
        movement_writer=movement_writer,
        ending_inventory_writer=ending_inventory_writer,
        ending_batch_writer=ending_batch_writer,
    )


def _group_csv_rows(path: Path) -> Iterator[tuple[str, list[dict[str, str]]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for branch_id, rows in groupby(reader, key=lambda row: row["branch_id"]):
            yield branch_id, list(rows)
