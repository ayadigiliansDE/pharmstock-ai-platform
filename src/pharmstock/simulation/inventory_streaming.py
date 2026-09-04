"""Partitioned, bounded-memory initial-inventory export for Stage 2D.

The Stage 2C generator remains available for small in-memory checkpoints.  This
module writes one branch at a time, closes each output partition, and never keeps
all branch/product or batch rows for the complete network in memory.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TextIO

from pharmstock.domain import Product
from pharmstock.simulation.inventory import (
    BranchAssortmentSummary,
    InitialBatchRow,
    InitialInventoryGenerator,
    InitialInventoryRow,
)
from pharmstock.simulation.network import GeneratedNetwork


@dataclass(frozen=True, slots=True)
class StreamingInventoryExportResult:
    """Small metadata result for a large partitioned export."""

    output_dir: Path
    manifest_path: Path
    success_marker_path: Path
    branch_summary_path: Path
    branch_count: int
    inventory_rows: int
    batch_rows: int
    total_initial_stock_units: int
    partition_count: int
    branches_per_partition: int
    catalog_size: int
    seed: int


@dataclass(slots=True)
class _PartitionWriters:
    stack: ExitStack
    inventory_handle: TextIO
    batch_handle: TextIO
    inventory_writer: csv.DictWriter
    batch_writer: csv.DictWriter
    partition_number: int

    def close(self) -> None:
        self.stack.close()


def export_initial_inventory_streaming(
    *,
    output_dir: Path,
    generator: InitialInventoryGenerator,
    network: GeneratedNetwork,
    products: Iterable[Product],
    branches_per_partition: int = 25,
    on_branch: Callable[[int, int, BranchAssortmentSummary], None] | None = None,
) -> StreamingInventoryExportResult:
    """Generate and immediately persist one branch at a time into CSV partitions."""

    if branches_per_partition <= 0:
        raise ValueError("branches_per_partition must be positive")

    catalog = tuple(product for product in products if product.regulatory_status.value == "active")
    if not catalog:
        raise ValueError("catalog must contain at least one active product")

    output_dir = output_dir.resolve()
    inventory_dir = output_dir / "inventory"
    batch_dir = output_dir / "batches"
    inventory_dir.mkdir(parents=True, exist_ok=True)
    batch_dir.mkdir(parents=True, exist_ok=True)

    # A rerun to the same checkpoint path must not leave stale partitions behind.
    for directory in (inventory_dir, batch_dir):
        for stale in directory.glob("part-*.csv"):
            stale.unlink()

    branch_summary_path = output_dir / "branch_assortment_summary.csv"
    manifest_path = output_dir / "inventory_manifest.json"
    success_marker_path = output_dir / "_SUCCESS"
    if success_marker_path.exists():
        success_marker_path.unlink()

    branch_count = 0
    inventory_row_count = 0
    batch_row_count = 0
    total_units = 0
    partition_count = 0
    by_scale: Counter[str] = Counter()
    inventory_skus_by_governorate: dict[str, int] = defaultdict(int)

    current: _PartitionWriters | None = None
    summary_handle: TextIO | None = None
    try:
        summary_handle = branch_summary_path.open("w", encoding="utf-8-sig", newline="")
        summary_writer: csv.DictWriter | None = None

        for index, generated_branch in enumerate(
            generator.iter_generate(network=network, products=catalog, on_branch=on_branch), start=1
        ):
            needed_partition = ((index - 1) // branches_per_partition) + 1
            if current is None or current.partition_number != needed_partition:
                if current is not None:
                    current.close()
                current = _open_partition(
                    inventory_dir=inventory_dir,
                    batch_dir=batch_dir,
                    partition_number=needed_partition,
                )
                partition_count = needed_partition

            if summary_writer is None:
                summary_fields = list(asdict(generated_branch.summary))
                summary_writer = csv.DictWriter(summary_handle, fieldnames=summary_fields)
                summary_writer.writeheader()
            summary_writer.writerow(asdict(generated_branch.summary))

            for row in generated_branch.inventory_rows:
                current.inventory_writer.writerow(asdict(row))
            for row in generated_branch.batch_rows:
                current.batch_writer.writerow(asdict(row))

            branch_count += 1
            inventory_row_count += len(generated_branch.inventory_rows)
            batch_row_count += len(generated_branch.batch_rows)
            total_units += generated_branch.summary.generated_stock_units
            by_scale[generated_branch.summary.branch_scale] += 1
            inventory_skus_by_governorate[
                generated_branch.summary.governorate
            ] += generated_branch.summary.generated_assortment_skus
    finally:
        if current is not None:
            current.close()
        if summary_handle is not None:
            summary_handle.close()

    manifest = {
        "stage": "2D",
        "export_mode": "bounded_memory_partitioned_csv",
        "seed": generator.seed,
        "catalog_products_available": len(catalog),
        "branch_count": branch_count,
        "branch_product_inventory_rows": inventory_row_count,
        "inventory_batch_rows": batch_row_count,
        "total_initial_stock_units": total_units,
        "average_skus_per_branch": (
            round(inventory_row_count / branch_count, 2) if branch_count else 0
        ),
        "partition_count": partition_count,
        "branches_per_partition": branches_per_partition,
        "branches_by_scale": dict(sorted(by_scale.items())),
        "inventory_skus_by_governorate": dict(sorted(inventory_skus_by_governorate.items())),
        "mapping_status": "synthetic_cross_market_mapping",
        "source_catalog_market": "US",
        "simulation_branch_market": "EG",
        "prices_generated": False,
        "memory_contract": (
            "one branch inventory retained at a time; "
            "completed branches are written and released"
        ),
        "inventory_partition_pattern": "inventory/part-XXXXX.csv",
        "batch_partition_pattern": "batches/part-XXXXX.csv",
        "completion_marker": "_SUCCESS",
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    success_marker_path.write_text("complete\n", encoding="utf-8")

    return StreamingInventoryExportResult(
        output_dir=output_dir,
        manifest_path=manifest_path,
        success_marker_path=success_marker_path,
        branch_summary_path=branch_summary_path,
        branch_count=branch_count,
        inventory_rows=inventory_row_count,
        batch_rows=batch_row_count,
        total_initial_stock_units=total_units,
        partition_count=partition_count,
        branches_per_partition=branches_per_partition,
        catalog_size=len(catalog),
        seed=generator.seed,
    )


def _open_partition(
    *, inventory_dir: Path, batch_dir: Path, partition_number: int
) -> _PartitionWriters:
    stack = ExitStack()
    inventory_handle = stack.enter_context(
        (inventory_dir / f"part-{partition_number:05d}.csv").open(
            "w", encoding="utf-8-sig", newline=""
        )
    )
    batch_handle = stack.enter_context(
        (batch_dir / f"part-{partition_number:05d}.csv").open(
            "w", encoding="utf-8-sig", newline=""
        )
    )
    inventory_fields = list(InitialInventoryRow.__dataclass_fields__)
    batch_fields = list(InitialBatchRow.__dataclass_fields__)
    inventory_writer = csv.DictWriter(inventory_handle, fieldnames=inventory_fields)
    batch_writer = csv.DictWriter(batch_handle, fieldnames=batch_fields)
    inventory_writer.writeheader()
    batch_writer.writeheader()
    return _PartitionWriters(
        stack=stack,
        inventory_handle=inventory_handle,
        batch_handle=batch_handle,
        inventory_writer=inventory_writer,
        batch_writer=batch_writer,
        partition_number=partition_number,
    )
