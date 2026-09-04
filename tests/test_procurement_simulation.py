import csv
import json
from pathlib import Path
from uuid import UUID

from pharmstock.simulation import (
    ProcurementSimulationPolicy,
    SupplierNetworkPolicy,
    build_synthetic_suppliers,
    export_procurement_cycle,
)
from pharmstock.simulation.network import PharmacyNetworkGenerator

PRODUCT_LOW = UUID("30000000-0000-0000-0000-000000000001")
PRODUCT_HEALTHY = UUID("30000000-0000-0000-0000-000000000002")
DEMAND_ID = UUID("60000000-0000-0000-0000-000000000001")


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _make_stage2e(tmp_path: Path) -> Path:
    stage2e = tmp_path / "stage2e"
    branch = PharmacyNetworkGenerator(seed=7).generate(1).branches[0]
    capacity = branch.capacity.storage_capacity_units
    healthy_units = capacity - 779
    low_units = 1

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
    inventory_rows = [
        {
            "inventory_item_id": "70000000-0000-0000-0000-000000000001",
            "branch_id": str(branch.branch_id),
            "organization_id": str(branch.organization_id),
            "branch_code": branch.branch_code,
            "governorate": branch.location.governorate,
            "branch_scale": branch.scale.value,
            "product_id": str(PRODUCT_LOW),
            "display_name": "Low Stock Medicine",
            "dosage_form": "TABLET",
            "ndc_product_code": "90000-00001",
            "ndc_package_code": "90000-00001-01",
            "source_market": "US",
            "simulation_market": "EG",
            "mapping_status": "synthetic_cross_market_mapping",
            "on_hand_quantity": low_units,
            "reserved_quantity": 0,
            "reorder_point": 10,
            "target_stock_level": 1000,
            "batch_count": 1,
            "inventory_version": 3,
        },
        {
            "inventory_item_id": "70000000-0000-0000-0000-000000000002",
            "branch_id": str(branch.branch_id),
            "organization_id": str(branch.organization_id),
            "branch_code": branch.branch_code,
            "governorate": branch.location.governorate,
            "branch_scale": branch.scale.value,
            "product_id": str(PRODUCT_HEALTHY),
            "display_name": "Healthy Stock Medicine",
            "dosage_form": "TABLET",
            "ndc_product_code": "90000-00002",
            "ndc_package_code": "90000-00002-01",
            "source_market": "US",
            "simulation_market": "EG",
            "mapping_status": "synthetic_cross_market_mapping",
            "on_hand_quantity": healthy_units,
            "reserved_quantity": 0,
            "reorder_point": 100,
            "target_stock_level": healthy_units + 1,
            "batch_count": 1,
            "inventory_version": 1,
        },
    ]
    _write_csv(stage2e / "ending_inventory" / "part-00001.csv", inventory_fields, inventory_rows)

    batch_fields = [
        "batch_id",
        "branch_id",
        "product_id",
        "batch_number",
        "received_on",
        "expires_on",
        "on_hand_quantity",
    ]
    _write_csv(
        stage2e / "ending_batches" / "part-00001.csv",
        batch_fields,
        [
            {
                "batch_id": "80000000-0000-0000-0000-000000000001",
                "branch_id": str(branch.branch_id),
                "product_id": str(PRODUCT_LOW),
                "batch_number": "OLD-LOW",
                "received_on": "2026-08-01",
                "expires_on": "2027-08-01",
                "on_hand_quantity": low_units,
            },
            {
                "batch_id": "80000000-0000-0000-0000-000000000002",
                "branch_id": str(branch.branch_id),
                "product_id": str(PRODUCT_HEALTHY),
                "batch_number": "OLD-HEALTHY",
                "received_on": "2026-08-01",
                "expires_on": "2027-08-01",
                "on_hand_quantity": healthy_units,
            },
        ],
    )

    reorder_fields = [
        "demand_id",
        "branch_id",
        "product_id",
        "occurred_at",
        "available_quantity",
        "reorder_point",
        "target_stock_level",
        "recommended_reorder_quantity",
        "inventory_version",
    ]
    _write_csv(
        stage2e / "reorder_triggers" / "part-00001.csv",
        reorder_fields,
        [
            {
                "demand_id": str(DEMAND_ID),
                "branch_id": str(branch.branch_id),
                "product_id": str(PRODUCT_LOW),
                "occurred_at": "2026-08-25T10:00:00+00:00",
                "available_quantity": 10,
                "reorder_point": 10,
                "target_stock_level": 1000,
                "recommended_reorder_quantity": 990,
                "inventory_version": 2,
            }
        ],
    )
    manifest = {
        "stage": "2E",
        "source_stage": "2D",
        "seed": 20260822,
        "source_inventory_seed": 7,
        "start_date": "2026-08-22",
        "days": 7,
        "branch_count": 1,
        "partition_count": 1,
        "monetary_values_generated": False,
    }
    stage2e.mkdir(parents=True, exist_ok=True)
    (stage2e / "demand_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (stage2e / "_SUCCESS").write_text("complete\n", encoding="utf-8")
    return stage2e


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_synthetic_supplier_master_is_deterministic() -> None:
    left = build_synthetic_suppliers(seed=99)
    right = build_synthetic_suppliers(seed=99)
    assert [(item.supplier_id, item.supplier_code) for item in left] == [
        (item.supplier_id, item.supplier_code) for item in right
    ]
    assert all(item.synthetic_record for item in left)


def test_supplier_policy_generates_national_and_regional_coverage() -> None:
    suppliers = build_synthetic_suppliers(seed=7, policy=ProcurementSimulationPolicy())
    assert len(suppliers) == 6
    assert {item.supplier_type.value for item in suppliers} == {
        "national_distributor",
        "regional_wholesaler",
    }


def test_procurement_requires_completed_stage2e(tmp_path: Path) -> None:
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    try:
        export_procurement_cycle(stage2e_dir=incomplete, output_dir=tmp_path / "out")
    except ValueError as exc:
        assert "_SUCCESS" in str(exc)
    else:
        raise AssertionError("incomplete Stage 2E input must fail")


def test_procurement_replenishes_without_exceeding_branch_capacity(tmp_path: Path) -> None:
    stage2e = _make_stage2e(tmp_path)
    output = tmp_path / "stage2f"
    result = export_procurement_cycle(stage2e_dir=stage2e, output_dir=output, seed=7)
    assert result.purchase_orders >= 1
    assert result.ordered_units == result.received_units
    assert result.deferred_units == 221
    kpi = _read_rows(output / "branch_procurement_kpis.csv")[0]
    assert int(kpi["final_units"]) == int(kpi["storage_capacity_units"])
    assert float(kpi["final_storage_utilization_pct"]) == 100.0


def test_procurement_outputs_are_explicitly_non_monetary_and_synthetic(tmp_path: Path) -> None:
    stage2e = _make_stage2e(tmp_path)
    output = tmp_path / "stage2f"
    export_procurement_cycle(stage2e_dir=stage2e, output_dir=output, seed=7)
    manifest = json.loads((output / "procurement_manifest.json").read_text(encoding="utf-8"))
    assert manifest["monetary_values_generated"] is False
    assert manifest["pricing_status"] == "not_simulated"
    assert "synthetic" in manifest["supplier_truth_boundary"].lower()
    suppliers = _read_rows(output / "supplier_master.csv")
    assert all(row["synthetic_record"] == "True" for row in suppliers)


def test_restock_receipt_creates_new_batch_and_positive_stock_movement(tmp_path: Path) -> None:
    stage2e = _make_stage2e(tmp_path)
    output = tmp_path / "stage2f"
    result = export_procurement_cycle(stage2e_dir=stage2e, output_dir=output, seed=7)
    movements = _read_rows(output / "restock_movements" / "part-00001.csv")
    receipts = _read_rows(output / "goods_receipt_lines" / "part-00001.csv")
    assert len(movements) == result.restock_movements
    assert all(int(row["quantity_delta"]) > 0 for row in movements)
    assert all(row["batch_number"].startswith("PROC-") for row in receipts)


def test_reorder_line_preserves_trigger_lineage(tmp_path: Path) -> None:
    stage2e = _make_stage2e(tmp_path)
    output = tmp_path / "stage2f"
    export_procurement_cycle(stage2e_dir=stage2e, output_dir=output, seed=7)
    lines = _read_rows(output / "purchase_order_lines" / "part-00001.csv")
    low = next(row for row in lines if row["product_id"] == str(PRODUCT_LOW))
    assert low["source_reorder_demand_id"] == str(DEMAND_ID)


def test_procurement_completion_marker_written_last_contract(tmp_path: Path) -> None:
    stage2e = _make_stage2e(tmp_path)
    output = tmp_path / "stage2f"
    result = export_procurement_cycle(stage2e_dir=stage2e, output_dir=output, seed=7)
    assert result.success_marker_path.exists()
    assert result.manifest_path.exists()


def test_scaled_supplier_network_integrates_with_procurement_cycle(tmp_path: Path) -> None:
    stage2e = _make_stage2e(tmp_path)
    output = tmp_path / "stage2f1"
    result = export_procurement_cycle(
        stage2e_dir=stage2e,
        output_dir=output,
        seed=7,
        supplier_network_policy=SupplierNetworkPolicy(),
        stage_label="2F.1",
    )
    manifest = json.loads((output / "procurement_manifest.json").read_text(encoding="utf-8"))
    suppliers = _read_rows(output / "supplier_master.csv")
    utilization = _read_rows(output / "supplier_utilization.csv")
    branch_kpi = _read_rows(output / "branch_procurement_kpis.csv")[0]
    panel = _read_rows(output / "branch_supplier_panels.csv")

    assert result.suppliers == 153
    assert result.suppliers_used >= 1
    assert len(suppliers) == 153
    assert len(utilization) == 153
    assert manifest["stage"] == "2F.1"
    assert manifest["supplier_network_mode"] == "scaled_supplier_ecosystem_v1"
    assert len(panel) == 12
    assert int(branch_kpi["supplier_panel_size"]) == 12
    assert int(branch_kpi["active_supplier_count"]) >= 1
