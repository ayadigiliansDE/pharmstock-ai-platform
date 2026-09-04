"""Synthetic branch-assortment and initial-inventory generation for Stage 2C.

This module intentionally does not claim that openFDA products are registered or sold
in Egypt.  When a U.S. source catalog is mapped to the synthetic Egyptian branch
network, every exported record is marked as a synthetic cross-market mapping.
"""

from __future__ import annotations

import csv
import json
import math
import random
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid5

from pharmstock.domain import InventoryItem, PharmacyBranch, PharmacyScale, Product, ReorderPolicy
from pharmstock.simulation.network import GeneratedNetwork

_INVENTORY_NAMESPACE = UUID("adfe5f4d-e587-4993-8c0d-64e1a10d7d65")


@dataclass(frozen=True, slots=True)
class InventorySimulationPolicy:
    """Explicit assumptions for synthetic initial branch inventory.

    Ratios represent how much of a branch's maximum SKU capacity is initially filled.
    They are simulation assumptions, not measured Egyptian pharmacy-market statistics.
    """

    small_fill_range: tuple[float, float] = (0.50, 0.68)
    medium_fill_range: tuple[float, float] = (0.58, 0.76)
    large_fill_range: tuple[float, float] = (0.64, 0.82)
    flagship_fill_range: tuple[float, float] = (0.70, 0.90)
    common_product_share: float = 0.78
    storage_fill_range: tuple[float, float] = (0.55, 0.78)
    min_stock_units: int = 2
    max_stock_units: int = 80
    max_batches_per_sku: int = 3

    def fill_range(self, scale: PharmacyScale) -> tuple[float, float]:
        ranges = {
            PharmacyScale.SMALL: self.small_fill_range,
            PharmacyScale.MEDIUM: self.medium_fill_range,
            PharmacyScale.LARGE: self.large_fill_range,
            PharmacyScale.FLAGSHIP: self.flagship_fill_range,
        }
        low, high = ranges[scale]
        if not 0 < low <= high <= 1:
            raise ValueError("assortment fill ranges must satisfy 0 < low <= high <= 1")
        return low, high

    def validate(self) -> None:
        for scale in PharmacyScale:
            self.fill_range(scale)
        if not 0 <= self.common_product_share <= 1:
            raise ValueError("common_product_share must be between 0 and 1")
        storage_low, storage_high = self.storage_fill_range
        if not 0 < storage_low <= storage_high <= 1:
            raise ValueError("storage_fill_range must satisfy 0 < low <= high <= 1")
        if self.min_stock_units <= 0 or self.max_stock_units < self.min_stock_units:
            raise ValueError("stock-unit bounds are invalid")
        if self.max_batches_per_sku <= 0:
            raise ValueError("max_batches_per_sku must be positive")


@dataclass(frozen=True, slots=True)
class InitialInventoryRow:
    inventory_item_id: str
    branch_id: str
    organization_id: str
    branch_code: str
    governorate: str
    branch_scale: str
    product_id: str
    display_name: str
    dosage_form: str
    ndc_product_code: str
    ndc_package_code: str
    source_market: str
    simulation_market: str
    mapping_status: str
    on_hand_quantity: int
    reserved_quantity: int
    reorder_point: int
    target_stock_level: int
    batch_count: int
    inventory_version: int


@dataclass(frozen=True, slots=True)
class InitialBatchRow:
    batch_id: str
    branch_id: str
    product_id: str
    batch_number: str
    received_on: str
    expires_on: str
    on_hand_quantity: int


@dataclass(frozen=True, slots=True)
class BranchAssortmentSummary:
    branch_id: str
    branch_code: str
    governorate: str
    branch_scale: str
    assortment_capacity_skus: int
    generated_assortment_skus: int
    storage_capacity_units: int
    generated_stock_units: int
    storage_utilization_pct: float


@dataclass(frozen=True, slots=True)
class GeneratedBranchInventory:
    """One branch worth of generated inventory, safe to write and release immediately."""

    inventory_rows: tuple[InitialInventoryRow, ...]
    batch_rows: tuple[InitialBatchRow, ...]
    summary: BranchAssortmentSummary


@dataclass(frozen=True, slots=True)
class GeneratedInitialInventory:
    inventory_rows: tuple[InitialInventoryRow, ...]
    batch_rows: tuple[InitialBatchRow, ...]
    branch_summaries: tuple[BranchAssortmentSummary, ...]
    seed: int
    catalog_size: int

    def summary(self) -> dict[str, object]:
        branch_count = len(self.branch_summaries)
        total_skus = len(self.inventory_rows)
        total_units = sum(row.on_hand_quantity for row in self.inventory_rows)
        by_scale = Counter(row.branch_scale for row in self.branch_summaries)
        by_governorate: dict[str, int] = defaultdict(int)
        for row in self.branch_summaries:
            by_governorate[row.governorate] += row.generated_assortment_skus
        return {
            "stage": "2C",
            "seed": self.seed,
            "catalog_products_available": self.catalog_size,
            "branch_count": branch_count,
            "branch_product_inventory_rows": total_skus,
            "inventory_batch_rows": len(self.batch_rows),
            "total_initial_stock_units": total_units,
            "average_skus_per_branch": round(total_skus / branch_count, 2) if branch_count else 0,
            "branches_by_scale": dict(sorted(by_scale.items())),
            "inventory_skus_by_governorate": dict(sorted(by_governorate.items())),
            "mapping_status": "synthetic_cross_market_mapping",
            "source_catalog_market": "US",
            "simulation_branch_market": "EG",
            "prices_generated": False,
        }


class InitialInventoryGenerator:
    """Generate deterministic branch assortments, stock and expiry batches."""

    def __init__(
        self,
        *,
        seed: int = 20260822,
        policy: InventorySimulationPolicy | None = None,
        reference_date: date | None = None,
    ) -> None:
        self.seed = seed
        self.policy = policy or InventorySimulationPolicy()
        self.policy.validate()
        self.reference_date = reference_date or datetime.now(UTC).date()
        self._rng = random.Random(seed)

    def _prepare_generation(
        self, *, network: GeneratedNetwork, products: Iterable[Product]
    ) -> tuple[tuple[Product, ...], tuple[Product, ...]]:
        catalog = tuple(
            product for product in products if product.regulatory_status.value == "active"
        )
        if not catalog:
            raise ValueError("catalog must contain at least one active product")
        if not network.branches:
            raise ValueError("network must contain at least one branch")
        return catalog, self._rank_catalog(catalog)

    def _generate_branch(
        self, *, branch: PharmacyBranch, ranked_products: tuple[Product, ...]
    ) -> GeneratedBranchInventory:
        selected = self._select_assortment(branch=branch, ranked_products=ranked_products)
        stock_quantities = self._allocate_branch_stock(branch=branch, products=selected)
        inventory_rows: list[InitialInventoryRow] = []
        batch_rows: list[InitialBatchRow] = []
        branch_units = 0

        for product, stock_quantity in zip(selected, stock_quantities, strict=True):
            reorder_point = max(1, math.floor(stock_quantity * self._rng.uniform(0.18, 0.32)))
            target_stock = max(
                reorder_point + 1,
                math.ceil(stock_quantity * self._rng.uniform(1.25, 1.70)),
            )
            item_id = uuid5(
                _INVENTORY_NAMESPACE,
                f"seed={self.seed}|branch={branch.branch_id}|product={product.product_id}",
            )
            inventory_item = InventoryItem(
                inventory_item_id=item_id,
                branch_id=branch.branch_id,
                product_id=product.product_id,
                on_hand_quantity=stock_quantity,
                reserved_quantity=0,
                reorder_policy=ReorderPolicy(
                    reorder_point=reorder_point,
                    target_stock_level=target_stock,
                ),
                updated_at=datetime.combine(
                    self.reference_date,
                    datetime.min.time(),
                    tzinfo=UTC,
                ),
            )
            generated_batches = self._generate_batches(
                branch=branch,
                product=product,
                quantity=stock_quantity,
            )
            batch_rows.extend(generated_batches)
            branch_units += stock_quantity
            inventory_rows.append(
                InitialInventoryRow(
                    inventory_item_id=str(inventory_item.inventory_item_id),
                    branch_id=str(branch.branch_id),
                    organization_id=str(branch.organization_id),
                    branch_code=branch.branch_code,
                    governorate=branch.location.governorate,
                    branch_scale=branch.scale.value,
                    product_id=str(product.product_id),
                    display_name=product.display_name,
                    dosage_form=product.dosage_form,
                    ndc_product_code=product.identifiers.ndc_product_code or "",
                    ndc_package_code=product.identifiers.ndc_package_code or "",
                    source_market=product.market_code,
                    simulation_market="EG",
                    mapping_status="synthetic_cross_market_mapping",
                    on_hand_quantity=inventory_item.on_hand_quantity,
                    reserved_quantity=inventory_item.reserved_quantity,
                    reorder_point=inventory_item.reorder_policy.reorder_point,
                    target_stock_level=inventory_item.reorder_policy.target_stock_level,
                    batch_count=len(generated_batches),
                    inventory_version=inventory_item.version,
                )
            )

        summary = BranchAssortmentSummary(
            branch_id=str(branch.branch_id),
            branch_code=branch.branch_code,
            governorate=branch.location.governorate,
            branch_scale=branch.scale.value,
            assortment_capacity_skus=branch.capacity.assortment_capacity_skus,
            generated_assortment_skus=len(selected),
            storage_capacity_units=branch.capacity.storage_capacity_units,
            generated_stock_units=branch_units,
            storage_utilization_pct=round(
                branch_units / branch.capacity.storage_capacity_units * 100, 2
            ),
        )
        return GeneratedBranchInventory(
            inventory_rows=tuple(inventory_rows),
            batch_rows=tuple(batch_rows),
            summary=summary,
        )

    def iter_generate(
        self,
        *,
        network: GeneratedNetwork,
        products: Iterable[Product],
        on_branch: Callable[[int, int, BranchAssortmentSummary], None] | None = None,
    ) -> Iterator[GeneratedBranchInventory]:
        """Yield one branch at a time so callers can write and release completed branches."""

        _, ranked_products = self._prepare_generation(network=network, products=products)
        for index, branch in enumerate(network.branches, start=1):
            generated_branch = self._generate_branch(
                branch=branch, ranked_products=ranked_products
            )
            if on_branch is not None:
                on_branch(index, len(network.branches), generated_branch.summary)
            yield generated_branch

    def generate(
        self,
        *,
        network: GeneratedNetwork,
        products: Iterable[Product],
        on_branch: Callable[[int, int, BranchAssortmentSummary], None] | None = None,
    ) -> GeneratedInitialInventory:
        """Generate the complete in-memory Stage 2C dataset (kept for checkpoint compatibility)."""

        catalog, ranked_products = self._prepare_generation(network=network, products=products)
        inventory_rows: list[InitialInventoryRow] = []
        batch_rows: list[InitialBatchRow] = []
        branch_summaries: list[BranchAssortmentSummary] = []

        for index, branch in enumerate(network.branches, start=1):
            generated_branch = self._generate_branch(
                branch=branch, ranked_products=ranked_products
            )
            inventory_rows.extend(generated_branch.inventory_rows)
            batch_rows.extend(generated_branch.batch_rows)
            branch_summaries.append(generated_branch.summary)
            if on_branch is not None:
                on_branch(index, len(network.branches), generated_branch.summary)

        return GeneratedInitialInventory(
            inventory_rows=tuple(inventory_rows),
            batch_rows=tuple(batch_rows),
            branch_summaries=tuple(branch_summaries),
            seed=self.seed,
            catalog_size=len(catalog),
        )

    def _rank_catalog(self, catalog: tuple[Product, ...]) -> tuple[Product, ...]:
        # Stable global popularity order. Oral solid/liquid products are modestly favored
        # as an explicit simulation assumption, never as a measured market-share claim.
        scored: list[tuple[float, str, Product]] = []
        for product in catalog:
            form = product.dosage_form.casefold()
            base = 1.0
            if any(token in form for token in ("tablet", "capsule", "solution", "suspension")):
                base += 0.35
            if "injection" in form:
                base -= 0.15
            jitter = self._rng.random()
            scored.append((-(base + jitter), str(product.product_id), product))
        scored.sort(key=lambda item: (item[0], item[1]))
        return tuple(product for _, _, product in scored)

    def _select_assortment(
        self, *, branch: PharmacyBranch, ranked_products: tuple[Product, ...]
    ) -> tuple[Product, ...]:
        low, high = self.policy.fill_range(branch.scale)
        target = round(branch.capacity.assortment_capacity_skus * self._rng.uniform(low, high))
        target = max(1, min(target, len(ranked_products)))
        common_count = min(target, round(target * self.policy.common_product_share))
        tail_count = target - common_count

        # Common core comes from a popularity-weighted top pool; tail adds branch diversity.
        common_pool_size = min(
            len(ranked_products),
            max(common_count, round(len(ranked_products) * 0.60)),
        )
        common_pool = ranked_products[:common_pool_size]
        common = self._rng.sample(common_pool, k=common_count) if common_count else []
        chosen_ids = {product.product_id for product in common}
        tail_pool = [product for product in ranked_products if product.product_id not in chosen_ids]
        tail = self._rng.sample(tail_pool, k=min(tail_count, len(tail_pool))) if tail_count else []
        return tuple(common + tail)

    def _allocate_branch_stock(
        self, *, branch: PharmacyBranch, products: tuple[Product, ...]
    ) -> tuple[int, ...]:
        """Allocate a branch-wide unit budget without exceeding physical storage capacity."""

        if not products:
            return ()
        minimum_total = len(products) * self.policy.min_stock_units
        if minimum_total > branch.capacity.storage_capacity_units:
            raise ValueError(
                "selected assortment cannot fit minimum units inside branch storage capacity"
            )

        low, high = self.policy.storage_fill_range
        target_units = round(branch.capacity.storage_capacity_units * self._rng.uniform(low, high))
        target_units = max(minimum_total, min(target_units, branch.capacity.storage_capacity_units))
        remaining = target_units - minimum_total

        weights: list[float] = []
        for product in products:
            form = product.dosage_form.casefold()
            form_multiplier = 1.0
            if any(token in form for token in ("tablet", "capsule")):
                form_multiplier = 1.25
            elif "injection" in form:
                form_multiplier = 0.70
            weights.append(self._rng.uniform(0.35, 1.65) * form_multiplier)

        total_weight = sum(weights)
        extras = [math.floor(remaining * weight / total_weight) for weight in weights]
        undistributed = remaining - sum(extras)
        order = list(range(len(products)))
        self._rng.shuffle(order)
        for index in order[:undistributed]:
            extras[index] += 1
        quantities = tuple(self.policy.min_stock_units + extra for extra in extras)
        if sum(quantities) != target_units:
            raise AssertionError("branch stock allocation must equal the branch stock budget")
        return quantities

    def _generate_batches(
        self, *, branch: PharmacyBranch, product: Product, quantity: int
    ) -> tuple[InitialBatchRow, ...]:
        batch_count = self._rng.randint(1, min(self.policy.max_batches_per_sku, quantity))
        remaining = quantity
        rows: list[InitialBatchRow] = []
        for batch_index in range(1, batch_count + 1):
            batches_left = batch_count - batch_index
            if batches_left == 0:
                batch_quantity = remaining
            else:
                max_for_batch = remaining - batches_left
                batch_quantity = self._rng.randint(1, max_for_batch)
            remaining -= batch_quantity
            received_days_ago = self._rng.randint(1, 120)
            received_on = self.reference_date - timedelta(days=received_days_ago)
            expires_on = self.reference_date + timedelta(days=self._rng.randint(120, 900))
            batch_number = (
                f"SIM-{branch.branch_code}-{str(product.product_id)[:8].upper()}-{batch_index:02d}"
            )
            batch_id = uuid5(
                _INVENTORY_NAMESPACE,
                (
                    f"seed={self.seed}|branch={branch.branch_id}|"
                    f"product={product.product_id}|batch={batch_index}"
                ),
            )
            rows.append(
                InitialBatchRow(
                    batch_id=str(batch_id),
                    branch_id=str(branch.branch_id),
                    product_id=str(product.product_id),
                    batch_number=batch_number,
                    received_on=received_on.isoformat(),
                    expires_on=expires_on.isoformat(),
                    on_hand_quantity=batch_quantity,
                )
            )
        if sum(row.on_hand_quantity for row in rows) != quantity:
            raise AssertionError("generated batch quantities must equal inventory on-hand quantity")
        return tuple(rows)


def export_initial_inventory(
    output_dir: Path, generated: GeneratedInitialInventory
) -> tuple[Path, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    inventory_path = output_dir / "branch_inventory.csv"
    batch_path = output_dir / "inventory_batches.csv"
    branch_summary_path = output_dir / "branch_assortment_summary.csv"
    summary_path = output_dir / "inventory_summary.json"

    _write_dataclass_csv(inventory_path, generated.inventory_rows)
    _write_dataclass_csv(batch_path, generated.batch_rows)
    _write_dataclass_csv(branch_summary_path, generated.branch_summaries)
    summary_path.write_text(
        json.dumps(generated.summary(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return inventory_path, batch_path, branch_summary_path, summary_path


def _write_dataclass_csv(path: Path, rows: tuple[object, ...]) -> None:
    if not rows:
        raise ValueError(f"cannot export empty dataset to {path}")
    first = asdict(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(first))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))
