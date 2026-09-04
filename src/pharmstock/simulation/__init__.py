"""Synthetic-data generators for local development and load simulation."""

from pharmstock.simulation.demand import (
    DemandLineRow,
    DemandSimulationPolicy,
    DemandSimulationResult,
    branch_is_open,
    export_demand_simulation,
)
from pharmstock.simulation.geography import (
    CAPMAS_POPULATION_2024_TOTAL,
    EGYPT_GOVERNORATES,
    EgyptRegion,
    GovernorateProfile,
    validate_governorate_reference,
)
from pharmstock.simulation.inventory import (
    BranchAssortmentSummary,
    GeneratedBranchInventory,
    GeneratedInitialInventory,
    InitialBatchRow,
    InitialInventoryGenerator,
    InitialInventoryRow,
    InventorySimulationPolicy,
    export_initial_inventory,
)
from pharmstock.simulation.inventory_streaming import (
    StreamingInventoryExportResult,
    export_initial_inventory_streaming,
)
from pharmstock.simulation.network import (
    GeneratedNetwork,
    NetworkSimulationPolicy,
    PharmacyNetworkGenerator,
    export_network,
)
from pharmstock.simulation.procurement import (
    ProcurementSimulationPolicy,
    ProcurementSimulationResult,
    build_synthetic_suppliers,
    export_procurement_cycle,
)
from pharmstock.simulation.production_network import (
    CAPMAS_GENERAL_PHARMACIES_2024,
    CAPMAS_PHARMACY_DENSITY_PER_1000,
    PROFILE_BRANCH_COUNTS,
    OwnershipMix,
    ProductionNetworkProfile,
    ProductionNetworkResult,
    ProductionPharmacyNetworkGenerator,
    export_production_network,
)
from pharmstock.simulation.suppliers import (
    SupplierAllocation,
    SupplierNetworkPolicy,
    allocate_supplier_quantities,
    build_branch_supplier_panel,
    build_scaled_supplier_network,
    supplier_carries_product,
    supplier_serves,
)

__all__ = [
    "CAPMAS_POPULATION_2024_TOTAL",
    "CAPMAS_GENERAL_PHARMACIES_2024",
    "CAPMAS_PHARMACY_DENSITY_PER_1000",
    "PROFILE_BRANCH_COUNTS",
    "DemandLineRow",
    "DemandSimulationPolicy",
    "DemandSimulationResult",
    "EGYPT_GOVERNORATES",
    "EgyptRegion",
    "BranchAssortmentSummary",
    "GeneratedBranchInventory",
    "GeneratedInitialInventory",
    "InitialBatchRow",
    "InitialInventoryGenerator",
    "InitialInventoryRow",
    "InventorySimulationPolicy",
    "GeneratedNetwork",
    "GovernorateProfile",
    "NetworkSimulationPolicy",
    "StreamingInventoryExportResult",
    "PharmacyNetworkGenerator",
    "OwnershipMix",
    "ProductionNetworkProfile",
    "ProductionNetworkResult",
    "ProductionPharmacyNetworkGenerator",
    "SupplierAllocation",
    "SupplierNetworkPolicy",
    "ProcurementSimulationPolicy",
    "ProcurementSimulationResult",
    "allocate_supplier_quantities",
    "branch_is_open",
    "build_branch_supplier_panel",
    "build_scaled_supplier_network",
    "build_synthetic_suppliers",
    "export_demand_simulation",
    "export_initial_inventory",
    "export_initial_inventory_streaming",
    "export_network",
    "export_production_network",
    "export_procurement_cycle",
    "supplier_carries_product",
    "supplier_serves",
    "validate_governorate_reference",
]
