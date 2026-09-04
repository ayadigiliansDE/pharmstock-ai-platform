"""Stage 2F.1 scalable synthetic supplier-network model.

The network deliberately uses fictional suppliers. Its purpose is to make the
procurement simulator structurally realistic at scale without pretending that
synthetic service metrics describe real Egyptian pharmaceutical distributors.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID, uuid5

from pharmstock.domain.procurement import SupplierProfile, SupplierType
from pharmstock.simulation.geography import EGYPT_GOVERNORATES, EgyptRegion

_SUPPLIER_NAMESPACE = UUID("35b26a6c-3fdc-4c47-b4b1-0dc25e85c31c")
_GOVERNORATES_BY_REGION = {
    region.value: tuple(item.name_en for item in EGYPT_GOVERNORATES if item.region is region)
    for region in EgyptRegion
}
_ALL_GOVERNORATES = tuple(item.name_en for item in EGYPT_GOVERNORATES)
_ALL_REGIONS = tuple(region.value for region in EgyptRegion)
_GOVERNORATE_REGION = {item.name_en: item.region.value for item in EGYPT_GOVERNORATES}


@dataclass(frozen=True, slots=True)
class SupplierNetworkPolicy:
    """Explicit scale assumptions for the Stage 2F.1 fictional supplier ecosystem."""

    national_distributors: int = 12
    regional_wholesalers_per_region: int = 6
    local_wholesalers_per_governorate: int = 3
    direct_manufacturers: int = 24
    cold_chain_specialists: int = 12
    preferred_supplier_panel_size: int = 12

    def validate(self) -> None:
        counts = (
            self.national_distributors,
            self.regional_wholesalers_per_region,
            self.local_wholesalers_per_governorate,
            self.direct_manufacturers,
            self.cold_chain_specialists,
        )
        if any(value <= 0 for value in counts):
            raise ValueError("all supplier-network counts must be positive")
        if not 5 <= self.preferred_supplier_panel_size <= 50:
            raise ValueError("preferred_supplier_panel_size must be between 5 and 50")

    @property
    def total_suppliers(self) -> int:
        return (
            self.national_distributors
            + self.regional_wholesalers_per_region * len(EgyptRegion)
            + self.local_wholesalers_per_governorate * len(EGYPT_GOVERNORATES)
            + self.direct_manufacturers
            + self.cold_chain_specialists
        )


@dataclass(frozen=True, slots=True)
class SupplierAllocation:
    supplier: SupplierProfile
    quantity: int


def build_scaled_supplier_network(
    *, seed: int, policy: SupplierNetworkPolicy | None = None
) -> tuple[SupplierProfile, ...]:
    """Build a deterministic fictional network sized for thousands of branches."""

    policy = policy or SupplierNetworkPolicy()
    policy.validate()
    suppliers: list[SupplierProfile] = []

    for index in range(1, policy.national_distributors + 1):
        code = f"SIM-NAT-{index:03d}"
        suppliers.append(
            _supplier(
                seed=seed,
                code=code,
                display_name=f"Synthetic National Distributor {index:03d}",
                supplier_type=SupplierType.NATIONAL_DISTRIBUTOR,
                regions=_ALL_REGIONS,
                governorates=_ALL_GOVERNORATES,
                lead_range=(2, 4),
                coverage_range=(0.78, 0.94),
                fill_range=(0.94, 0.995),
                reliability_range=(0.92, 0.99),
                capacity_range=(180_000, 420_000),
                cold_chain=index % 3 != 0,
            )
        )

    for region in EgyptRegion:
        governorates = _GOVERNORATES_BY_REGION[region.value]
        for index in range(1, policy.regional_wholesalers_per_region + 1):
            code = f"SIM-REG-{region.name[:3]}-{index:03d}"
            suppliers.append(
                _supplier(
                    seed=seed,
                    code=code,
                    display_name=(
                        f"Synthetic {region.value.replace('_', ' ').title()} Regional "
                        f"Wholesaler {index:03d}"
                    ),
                    supplier_type=SupplierType.REGIONAL_WHOLESALER,
                    regions=(region.value,),
                    governorates=governorates,
                    lead_range=(1, 3),
                    coverage_range=(0.45, 0.72),
                    fill_range=(0.90, 0.98),
                    reliability_range=(0.88, 0.97),
                    capacity_range=(70_000, 180_000),
                    cold_chain=index % 2 == 0,
                )
            )

    for governorate in EGYPT_GOVERNORATES:
        for index in range(1, policy.local_wholesalers_per_governorate + 1):
            code = f"SIM-LOC-{governorate.code}-{index:02d}"
            suppliers.append(
                _supplier(
                    seed=seed,
                    code=code,
                    display_name=(
                        f"Synthetic {governorate.name_en} Local Wholesaler {index:02d}"
                    ),
                    supplier_type=SupplierType.LOCAL_WHOLESALER,
                    regions=(governorate.region.value,),
                    governorates=(governorate.name_en,),
                    lead_range=(1, 2),
                    coverage_range=(0.18, 0.45),
                    fill_range=(0.84, 0.96),
                    reliability_range=(0.82, 0.95),
                    capacity_range=(18_000, 60_000),
                    cold_chain=index == 1,
                )
            )

    for index in range(1, policy.direct_manufacturers + 1):
        code = f"SIM-MFG-{index:03d}"
        suppliers.append(
            _supplier(
                seed=seed,
                code=code,
                display_name=f"Synthetic Direct Manufacturer {index:03d}",
                supplier_type=SupplierType.DIRECT_MANUFACTURER,
                regions=_ALL_REGIONS,
                governorates=_ALL_GOVERNORATES,
                lead_range=(2, 5),
                coverage_range=(0.02, 0.08),
                fill_range=(0.95, 0.995),
                reliability_range=(0.93, 0.995),
                capacity_range=(25_000, 100_000),
                cold_chain=index % 4 == 0,
            )
        )

    for index in range(1, policy.cold_chain_specialists + 1):
        code = f"SIM-COLD-{index:03d}"
        suppliers.append(
            _supplier(
                seed=seed,
                code=code,
                display_name=f"Synthetic Cold Chain Specialist {index:03d}",
                supplier_type=SupplierType.COLD_CHAIN_SPECIALIST,
                regions=_ALL_REGIONS,
                governorates=_ALL_GOVERNORATES,
                lead_range=(1, 3),
                coverage_range=(0.04, 0.15),
                fill_range=(0.90, 0.99),
                reliability_range=(0.90, 0.99),
                capacity_range=(12_000, 50_000),
                cold_chain=True,
            )
        )

    if len(suppliers) != policy.total_suppliers:
        raise AssertionError("generated supplier count does not match policy")
    return tuple(suppliers)


def build_branch_supplier_panel(
    *,
    suppliers: tuple[SupplierProfile, ...],
    branch_id: UUID,
    governorate: str,
    panel_size: int,
) -> tuple[SupplierProfile, ...]:
    """Select a stable preferred supplier panel instead of using the whole network."""

    eligible = [supplier for supplier in suppliers if supplier_serves(supplier, governorate)]
    if not eligible:
        raise ValueError(f"no synthetic supplier serves governorate {governorate}")

    quotas = {
        SupplierType.NATIONAL_DISTRIBUTOR: 4,
        SupplierType.REGIONAL_WHOLESALER: 3,
        SupplierType.LOCAL_WHOLESALER: 2,
        SupplierType.DIRECT_MANUFACTURER: 2,
        SupplierType.COLD_CHAIN_SPECIALIST: 1,
    }
    selected: list[SupplierProfile] = []
    for supplier_type, quota in quotas.items():
        typed = [item for item in eligible if item.supplier_type is supplier_type]
        typed.sort(key=lambda item: _branch_rank(branch_id, governorate, item), reverse=True)
        selected.extend(typed[:quota])

    seen = {item.supplier_id for item in selected}
    remaining = [item for item in eligible if item.supplier_id not in seen]
    remaining.sort(key=lambda item: _branch_rank(branch_id, governorate, item), reverse=True)
    selected.extend(remaining[: max(panel_size - len(selected), 0)])
    return tuple(selected[:panel_size])


def allocate_supplier_quantities(
    *,
    suppliers: tuple[SupplierProfile, ...],
    preferred_panel: tuple[SupplierProfile, ...],
    governorate: str,
    product_id: UUID,
    required_quantity: int,
    capacity_remaining: dict[UUID, int],
) -> tuple[tuple[SupplierAllocation, ...], int]:
    """Allocate one product across suitable suppliers, falling back beyond the branch panel."""

    if required_quantity <= 0:
        return (), 0

    panel_ranked = _rank_product_suppliers(
        suppliers=preferred_panel,
        governorate=governorate,
        product_id=product_id,
    )
    panel_ids = {item.supplier_id for item in panel_ranked}
    fallback = _rank_product_suppliers(
        suppliers=tuple(item for item in suppliers if item.supplier_id not in panel_ids),
        governorate=governorate,
        product_id=product_id,
    )
    ranked = (*panel_ranked, *fallback)

    remaining = required_quantity
    allocations: list[SupplierAllocation] = []
    for supplier in ranked:
        available = max(capacity_remaining.get(supplier.supplier_id, 0), 0)
        if available <= 0:
            continue
        quantity = min(remaining, available)
        if quantity <= 0:
            continue
        allocations.append(SupplierAllocation(supplier=supplier, quantity=quantity))
        capacity_remaining[supplier.supplier_id] = available - quantity
        remaining -= quantity
        if remaining == 0:
            break
    return tuple(allocations), remaining


def supplier_serves(supplier: SupplierProfile, governorate: str) -> bool:
    if supplier.service_governorates:
        return governorate in supplier.service_governorates
    region = _GOVERNORATE_REGION[governorate]
    return region in supplier.service_regions


def supplier_carries_product(supplier: SupplierProfile, product_id: UUID) -> bool:
    if supplier.catalog_coverage_ratio >= 1.0:
        return True
    score = _unit_interval(f"supplier={supplier.supplier_id}|product={product_id}")
    return score < supplier.catalog_coverage_ratio


def _rank_product_suppliers(
    *, suppliers: tuple[SupplierProfile, ...], governorate: str, product_id: UUID
) -> tuple[SupplierProfile, ...]:
    eligible = [
        supplier
        for supplier in suppliers
        if supplier_serves(supplier, governorate) and supplier_carries_product(supplier, product_id)
    ]
    eligible.sort(
        key=lambda supplier: _product_supplier_score(supplier, governorate, product_id),
        reverse=True,
    )
    return tuple(eligible)


def _product_supplier_score(
    supplier: SupplierProfile, governorate: str, product_id: UUID
) -> float:
    locality = 0.0
    if supplier.supplier_type is SupplierType.LOCAL_WHOLESALER:
        locality = 0.10
    elif supplier.supplier_type is SupplierType.REGIONAL_WHOLESALER:
        locality = 0.06
    elif supplier.supplier_type is SupplierType.NATIONAL_DISTRIBUTOR:
        locality = 0.03
    affinity = _unit_interval(
        f"product-affinity|supplier={supplier.supplier_id}|product={product_id}|gov={governorate}"
    )
    lead_component = 1.0 / supplier.base_lead_time_days
    return (
        supplier.reliability_score * 0.32
        + supplier.expected_fill_rate * 0.28
        + lead_component * 0.15
        + affinity * 0.15
        + locality
    )


def _branch_rank(branch_id: UUID, governorate: str, supplier: SupplierProfile) -> float:
    affinity = _unit_interval(
        f"branch-affinity|branch={branch_id}|supplier={supplier.supplier_id}|gov={governorate}"
    )
    lead_component = 1.0 / supplier.base_lead_time_days
    return (
        supplier.reliability_score * 0.35
        + supplier.expected_fill_rate * 0.25
        + lead_component * 0.15
        + affinity * 0.25
    )


def _supplier(
    *,
    seed: int,
    code: str,
    display_name: str,
    supplier_type: SupplierType,
    regions: tuple[str, ...],
    governorates: tuple[str, ...],
    lead_range: tuple[int, int],
    coverage_range: tuple[float, float],
    fill_range: tuple[float, float],
    reliability_range: tuple[float, float],
    capacity_range: tuple[int, int],
    cold_chain: bool,
) -> SupplierProfile:
    return SupplierProfile(
        supplier_id=uuid5(_SUPPLIER_NAMESPACE, f"seed={seed}|supplier={code}"),
        supplier_code=code,
        display_name=display_name,
        supplier_type=supplier_type,
        base_lead_time_days=_int_range(seed, code, "lead", *lead_range),
        service_regions=regions,
        service_governorates=governorates,
        catalog_coverage_ratio=round(
            _float_range(seed, code, "coverage", *coverage_range), 4
        ),
        expected_fill_rate=round(_float_range(seed, code, "fill", *fill_range), 4),
        reliability_score=round(
            _float_range(seed, code, "reliability", *reliability_range), 4
        ),
        cycle_capacity_units=_int_range(seed, code, "capacity", *capacity_range),
        cold_chain_supported=cold_chain,
    )


def _float_range(seed: int, code: str, metric: str, low: float, high: float) -> float:
    return low + (high - low) * _unit_interval(f"seed={seed}|supplier={code}|metric={metric}")


def _int_range(seed: int, code: str, metric: str, low: int, high: int) -> int:
    span = high - low + 1
    raw = int.from_bytes(
        hashlib.sha256(f"seed={seed}|supplier={code}|metric={metric}".encode()).digest()[:8],
        "big",
    )
    return low + raw % span


def _unit_interval(token: str) -> float:
    raw = int.from_bytes(hashlib.sha256(token.encode()).digest()[:8], "big")
    return raw / ((1 << 64) - 1)
