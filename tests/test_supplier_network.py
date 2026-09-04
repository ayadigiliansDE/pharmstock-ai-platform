from uuid import UUID

from pharmstock.domain import SupplierType
from pharmstock.simulation.suppliers import (
    SupplierNetworkPolicy,
    allocate_supplier_quantities,
    build_branch_supplier_panel,
    build_scaled_supplier_network,
    supplier_carries_product,
    supplier_serves,
)

BRANCH_ID = UUID("10000000-0000-0000-0000-000000000001")
PRODUCT_ID = UUID("20000000-0000-0000-0000-000000000001")


def test_default_scaled_network_has_153_suppliers() -> None:
    policy = SupplierNetworkPolicy()
    suppliers = build_scaled_supplier_network(seed=7, policy=policy)
    assert policy.total_suppliers == 153
    assert len(suppliers) == 153


def test_scaled_network_contains_all_supplier_archetypes() -> None:
    suppliers = build_scaled_supplier_network(seed=7)
    counts = {supplier_type: 0 for supplier_type in SupplierType}
    for supplier in suppliers:
        counts[supplier.supplier_type] += 1
    assert counts[SupplierType.NATIONAL_DISTRIBUTOR] == 12
    assert counts[SupplierType.REGIONAL_WHOLESALER] == 24
    assert counts[SupplierType.LOCAL_WHOLESALER] == 81
    assert counts[SupplierType.DIRECT_MANUFACTURER] == 24
    assert counts[SupplierType.COLD_CHAIN_SPECIALIST] == 12


def test_scaled_supplier_master_is_deterministic() -> None:
    left = build_scaled_supplier_network(seed=99)
    right = build_scaled_supplier_network(seed=99)
    assert left == right


def test_local_wholesaler_only_serves_its_governorate() -> None:
    suppliers = build_scaled_supplier_network(seed=7)
    cairo_local = next(
        supplier
        for supplier in suppliers
        if supplier.supplier_type is SupplierType.LOCAL_WHOLESALER
        and supplier.service_governorates == ("Cairo",)
    )
    assert supplier_serves(cairo_local, "Cairo") is True
    assert supplier_serves(cairo_local, "Giza") is False


def test_branch_supplier_panel_is_limited_and_geographically_valid() -> None:
    suppliers = build_scaled_supplier_network(seed=7)
    panel = build_branch_supplier_panel(
        suppliers=suppliers,
        branch_id=BRANCH_ID,
        governorate="Minya",
        panel_size=12,
    )
    assert len(panel) == 12
    assert len({supplier.supplier_id for supplier in panel}) == 12
    assert all(supplier_serves(supplier, "Minya") for supplier in panel)
    assert {supplier.supplier_type for supplier in panel} == set(SupplierType)


def test_catalog_coverage_is_product_stable() -> None:
    supplier = build_scaled_supplier_network(seed=7)[0]
    assert supplier_carries_product(supplier, PRODUCT_ID) == supplier_carries_product(
        supplier, PRODUCT_ID
    )


def test_allocation_respects_supplier_cycle_capacity() -> None:
    suppliers = build_scaled_supplier_network(seed=7)
    panel = build_branch_supplier_panel(
        suppliers=suppliers,
        branch_id=BRANCH_ID,
        governorate="Cairo",
        panel_size=12,
    )
    capacity = {supplier.supplier_id: 0 for supplier in suppliers}
    capable = next(
        supplier
        for supplier in suppliers
        if supplier_serves(supplier, "Cairo") and supplier_carries_product(supplier, PRODUCT_ID)
    )
    capacity[capable.supplier_id] = 5
    allocations, deferred = allocate_supplier_quantities(
        suppliers=suppliers,
        preferred_panel=panel,
        governorate="Cairo",
        product_id=PRODUCT_ID,
        required_quantity=8,
        capacity_remaining=capacity,
    )
    assert sum(item.quantity for item in allocations) == 5
    assert deferred == 3
    assert capacity[capable.supplier_id] == 0


def test_scaled_profiles_have_nontrivial_service_metrics() -> None:
    suppliers = build_scaled_supplier_network(seed=7)
    assert any(supplier.catalog_coverage_ratio < 1.0 for supplier in suppliers)
    assert any(supplier.expected_fill_rate < 1.0 for supplier in suppliers)
    assert any(supplier.reliability_score < 1.0 for supplier in suppliers)
    assert any(supplier.cold_chain_supported for supplier in suppliers)
    assert all(supplier.cycle_capacity_units >= 100 for supplier in suppliers)
