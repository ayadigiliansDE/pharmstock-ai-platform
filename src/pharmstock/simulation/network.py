"""Deterministic, large-scale synthetic pharmacy-network generation.

The generated businesses are intentionally fictional. Real CAPMAS population estimates
are used only to weight governorate allocation. Business ownership, branch scale,
capacity and service patterns are simulation assumptions and are kept explicit here.
"""

from __future__ import annotations

import csv
import json
import math
import random
from collections import Counter
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from uuid import UUID, uuid5

from pharmstock.domain import (
    BranchLocation,
    CapacityProfile,
    DailyOperatingHours,
    OperatingProfile,
    OrganizationType,
    PharmacyBranch,
    PharmacyOrganization,
    PharmacyScale,
    PharmacyType,
    ServiceMode,
    Weekday,
)
from pharmstock.simulation.geography import EGYPT_GOVERNORATES, GovernorateProfile

_SIMULATION_NAMESPACE = UUID("7df7f4ab-f7bb-4c94-aaac-427e8bddc0bb")


@dataclass(frozen=True, slots=True)
class NetworkSimulationPolicy:
    """Explicit assumptions for synthetic business characteristics.

    These are not claimed to be official Egyptian pharmacy-market shares. They are
    simulator defaults that can be replaced later by measured market data.
    """

    independent_share: float = 0.58
    chain_share: float = 0.34
    hospital_network_share: float = 0.06
    digital_operator_share: float = 0.02

    def ownership_weights(self) -> tuple[tuple[OrganizationType, float], ...]:
        values = (
            (OrganizationType.INDEPENDENT, self.independent_share),
            (OrganizationType.CHAIN, self.chain_share),
            (OrganizationType.HOSPITAL_NETWORK, self.hospital_network_share),
            (OrganizationType.DIGITAL_OPERATOR, self.digital_operator_share),
        )
        total = sum(weight for _, weight in values)
        if not math.isclose(total, 1.0, abs_tol=1e-9):
            raise ValueError("organization shares must sum to 1.0")
        if any(weight < 0 for _, weight in values):
            raise ValueError("organization shares cannot be negative")
        return values


@dataclass(frozen=True, slots=True)
class GeneratedNetwork:
    organizations: tuple[PharmacyOrganization, ...]
    branches: tuple[PharmacyBranch, ...]
    seed: int

    def summary(self) -> dict[str, object]:
        by_governorate = Counter(branch.location.governorate for branch in self.branches)
        by_scale = Counter(branch.scale.value for branch in self.branches)
        by_type = Counter(branch.pharmacy_type.value for branch in self.branches)
        by_org_type = Counter(org.organization_type.value for org in self.organizations)
        return {
            "seed": self.seed,
            "organization_count": len(self.organizations),
            "branch_count": len(self.branches),
            "governorate_count": len(by_governorate),
            "branches_by_governorate": dict(sorted(by_governorate.items())),
            "branches_by_scale": dict(sorted(by_scale.items())),
            "branches_by_pharmacy_type": dict(sorted(by_type.items())),
            "organizations_by_type": dict(sorted(by_org_type.items())),
        }


class PharmacyNetworkGenerator:
    """Generate fictional pharmacy organizations and branches at configurable scale."""

    def __init__(self, *, seed: int = 20260822, policy: NetworkSimulationPolicy | None = None):
        self.seed = seed
        self.policy = policy or NetworkSimulationPolicy()
        self.policy.ownership_weights()
        self._rng = random.Random(seed)

    def generate(self, branch_count: int) -> GeneratedNetwork:
        if branch_count <= 0:
            raise ValueError("branch_count must be positive")

        governorate_counts = _allocate_governorates(branch_count)
        org_branch_targets = self._organization_branch_targets(branch_count)
        organizations = self._build_organizations(org_branch_targets)
        branches = self._build_branches(
            governorate_counts=governorate_counts,
            organizations=organizations,
            org_branch_targets=org_branch_targets,
        )
        return GeneratedNetwork(tuple(organizations), tuple(branches), self.seed)

    def _organization_branch_targets(self, branch_count: int) -> list[tuple[OrganizationType, int]]:
        """Create organizations until their planned branch counts cover the target network."""

        weighted_types, weights = zip(*self.policy.ownership_weights(), strict=True)
        targets: list[tuple[OrganizationType, int]] = []
        remaining = branch_count
        while remaining > 0:
            org_type = self._rng.choices(weighted_types, weights=weights, k=1)[0]
            if org_type is OrganizationType.INDEPENDENT:
                planned = 1
            elif org_type is OrganizationType.CHAIN:
                planned = self._rng.randint(3, 35)
            elif org_type is OrganizationType.HOSPITAL_NETWORK:
                planned = self._rng.randint(1, 8)
            else:
                planned = self._rng.randint(1, 5)
            planned = min(planned, remaining)
            targets.append((org_type, planned))
            remaining -= planned
        return targets

    def _build_organizations(
        self, targets: list[tuple[OrganizationType, int]]
    ) -> list[PharmacyOrganization]:
        counters: Counter[OrganizationType] = Counter()
        organizations: list[PharmacyOrganization] = []
        prefixes = {
            OrganizationType.INDEPENDENT: "IND",
            OrganizationType.CHAIN: "CHN",
            OrganizationType.HOSPITAL_NETWORK: "HSP",
            OrganizationType.DIGITAL_OPERATOR: "DIG",
        }
        labels = {
            OrganizationType.INDEPENDENT: "Independent Pharmacy",
            OrganizationType.CHAIN: "Pharmacy Group",
            OrganizationType.HOSPITAL_NETWORK: "Hospital Pharmacy Network",
            OrganizationType.DIGITAL_OPERATOR: "Digital Pharmacy Operator",
        }

        for org_type, _ in targets:
            counters[org_type] += 1
            index = counters[org_type]
            code = f"SIM-{prefixes[org_type]}-{index:05d}"
            org_id = uuid5(_SIMULATION_NAMESPACE, f"seed={self.seed}|org={code}")
            display = f"Synthetic {labels[org_type]} {index:05d}"
            organizations.append(
                PharmacyOrganization(
                    organization_id=org_id,
                    organization_code=code,
                    legal_name=f"{display} SAE",
                    display_name=display,
                    organization_type=org_type,
                    market_code="EG",
                )
            )
        return organizations

    def _build_branches(
        self,
        *,
        governorate_counts: dict[str, int],
        organizations: list[PharmacyOrganization],
        org_branch_targets: list[tuple[OrganizationType, int]],
    ) -> list[PharmacyBranch]:
        governorate_queue: list[GovernorateProfile] = []
        profile_by_code = {profile.code: profile for profile in EGYPT_GOVERNORATES}
        for code, count in governorate_counts.items():
            governorate_queue.extend([profile_by_code[code]] * count)
        self._rng.shuffle(governorate_queue)

        branches: list[PharmacyBranch] = []
        global_index = 0
        for organization, (_, planned_branches) in zip(
            organizations, org_branch_targets, strict=True
        ):
            for org_branch_index in range(1, planned_branches + 1):
                global_index += 1
                governorate = governorate_queue.pop()
                branch_code = f"{governorate.code}-SIM-{global_index:06d}"
                scale = self._choose_scale(organization.organization_type)
                pharmacy_type = self._choose_pharmacy_type(organization.organization_type)
                branch_id = uuid5(
                    _SIMULATION_NAMESPACE,
                    f"seed={self.seed}|branch={branch_code}|org={organization.organization_code}",
                )
                branches.append(
                    PharmacyBranch(
                        branch_id=branch_id,
                        organization_id=organization.organization_id,
                        branch_code=branch_code,
                        display_name=(
                            f"{organization.display_name} - {governorate.representative_city} "
                            f"{org_branch_index:03d}"
                        ),
                        pharmacy_type=pharmacy_type,
                        scale=scale,
                        location=BranchLocation(
                            country_code="EG",
                            governorate=governorate.name_en,
                            city=governorate.representative_city,
                        ),
                        operating_profile=self._operating_profile(
                            scale=scale, pharmacy_type=pharmacy_type
                        ),
                        capacity=self._capacity_profile(scale),
                    )
                )

        if governorate_queue:
            raise RuntimeError("internal allocation error: unused governorate slots")
        return branches

    def _choose_scale(self, org_type: OrganizationType) -> PharmacyScale:
        if org_type is OrganizationType.INDEPENDENT:
            return self._rng.choices(
                [PharmacyScale.SMALL, PharmacyScale.MEDIUM, PharmacyScale.LARGE],
                weights=[0.58, 0.34, 0.08],
                k=1,
            )[0]
        if org_type is OrganizationType.CHAIN:
            return self._rng.choices(
                [
                    PharmacyScale.SMALL,
                    PharmacyScale.MEDIUM,
                    PharmacyScale.LARGE,
                    PharmacyScale.FLAGSHIP,
                ],
                weights=[0.18, 0.50, 0.27, 0.05],
                k=1,
            )[0]
        if org_type is OrganizationType.HOSPITAL_NETWORK:
            return self._rng.choices(
                [PharmacyScale.MEDIUM, PharmacyScale.LARGE, PharmacyScale.FLAGSHIP],
                weights=[0.30, 0.55, 0.15],
                k=1,
            )[0]
        return self._rng.choices(
            [PharmacyScale.MEDIUM, PharmacyScale.LARGE, PharmacyScale.FLAGSHIP],
            weights=[0.15, 0.55, 0.30],
            k=1,
        )[0]

    def _choose_pharmacy_type(self, org_type: OrganizationType) -> PharmacyType:
        if org_type is OrganizationType.HOSPITAL_NETWORK:
            return PharmacyType.HOSPITAL
        if org_type is OrganizationType.DIGITAL_OPERATOR:
            return PharmacyType.FULFILLMENT_CENTER
        return PharmacyType.COMMUNITY

    def _capacity_profile(self, scale: PharmacyScale) -> CapacityProfile:
        ranges = {
            PharmacyScale.SMALL: ((700, 1_600), (6_000, 18_000), (45, 110), (1, 2)),
            PharmacyScale.MEDIUM: ((1_800, 4_000), (15_000, 45_000), (90, 240), (2, 5)),
            PharmacyScale.LARGE: ((4_000, 8_500), (35_000, 110_000), (180, 600), (4, 10)),
            PharmacyScale.FLAGSHIP: (
                (7_500, 15_000),
                (80_000, 300_000),
                (450, 1_500),
                (8, 25),
            ),
        }
        sku_range, unit_range, floor_range, checkout_range = ranges[scale]
        skus = self._rng.randint(*sku_range)
        units = max(self._rng.randint(*unit_range), skus)
        cold_chain = self._rng.random() < {
            PharmacyScale.SMALL: 0.72,
            PharmacyScale.MEDIUM: 0.88,
            PharmacyScale.LARGE: 0.96,
            PharmacyScale.FLAGSHIP: 0.99,
        }[scale]
        cold_capacity = self._rng.randint(80, max(100, units // 12)) if cold_chain else 0
        return CapacityProfile(
            assortment_capacity_skus=skus,
            storage_capacity_units=units,
            floor_area_m2=float(self._rng.randint(*floor_range)),
            checkout_points=self._rng.randint(*checkout_range),
            cold_chain_supported=cold_chain,
            cold_chain_capacity_units=cold_capacity,
        )

    def _operating_profile(
        self, *, scale: PharmacyScale, pharmacy_type: PharmacyType
    ) -> OperatingProfile:
        is_24_7 = (
            pharmacy_type in {PharmacyType.HOSPITAL, PharmacyType.FULFILLMENT_CENTER}
            or (
                scale in {PharmacyScale.LARGE, PharmacyScale.FLAGSHIP}
                and self._rng.random() < 0.35
            )
        )
        if is_24_7:
            schedule = tuple(
                DailyOperatingHours(weekday=weekday, is_24_hours=True) for weekday in Weekday
            )
        else:
            opens = time(8, 0) if scale is not PharmacyScale.SMALL else time(9, 0)
            closes = (
                time(0, 0)
                if scale in {PharmacyScale.LARGE, PharmacyScale.FLAGSHIP}
                else time(23, 0)
            )
            schedule = tuple(
                DailyOperatingHours(weekday=weekday, opens_at=opens, closes_at=closes)
                for weekday in Weekday
            )

        modes = {ServiceMode.IN_STORE}
        if pharmacy_type is PharmacyType.FULFILLMENT_CENTER:
            modes = {ServiceMode.DELIVERY, ServiceMode.ONLINE_FULFILLMENT}
        else:
            if scale is not PharmacyScale.SMALL or self._rng.random() < 0.45:
                modes.add(ServiceMode.DELIVERY)
            if scale in {PharmacyScale.LARGE, PharmacyScale.FLAGSHIP}:
                modes.add(ServiceMode.CLICK_AND_COLLECT)

        return OperatingProfile(
            timezone="Africa/Cairo",
            schedule=schedule,
            service_modes=frozenset(modes),
            emergency_service=pharmacy_type is PharmacyType.HOSPITAL,
        )


def _allocate_governorates(branch_count: int) -> dict[str, int]:
    """Allocate branches using CAPMAS population weights via largest remainder."""

    total_population = sum(item.population_2024 for item in EGYPT_GOVERNORATES)
    raw = {
        item.code: branch_count * item.population_2024 / total_population
        for item in EGYPT_GOVERNORATES
    }
    allocation = {code: math.floor(value) for code, value in raw.items()}
    remaining = branch_count - sum(allocation.values())
    ranked = sorted(raw, key=lambda code: (raw[code] - allocation[code], code), reverse=True)
    for code in ranked[:remaining]:
        allocation[code] += 1
    return allocation


def export_network(network: GeneratedNetwork, output_dir: str | Path) -> tuple[Path, Path, Path]:
    """Export human-readable network artifacts for local inspection."""

    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    org_path = target / "pharmacy_organizations.csv"
    branch_path = target / "pharmacy_branches.csv"
    summary_path = target / "network_summary.json"

    with org_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "organization_id",
                "organization_code",
                "legal_name",
                "display_name",
                "organization_type",
                "market_code",
            ],
        )
        writer.writeheader()
        for org in network.organizations:
            writer.writerow(
                {
                    "organization_id": str(org.organization_id),
                    "organization_code": org.organization_code,
                    "legal_name": org.legal_name,
                    "display_name": org.display_name,
                    "organization_type": org.organization_type.value,
                    "market_code": org.market_code,
                }
            )

    with branch_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "branch_id",
                "organization_id",
                "branch_code",
                "display_name",
                "pharmacy_type",
                "scale",
                "governorate",
                "city",
                "assortment_capacity_skus",
                "storage_capacity_units",
                "floor_area_m2",
                "checkout_points",
                "cold_chain_supported",
                "cold_chain_capacity_units",
                "service_modes",
                "timezone",
            ],
        )
        writer.writeheader()
        for branch in network.branches:
            writer.writerow(
                {
                    "branch_id": str(branch.branch_id),
                    "organization_id": str(branch.organization_id),
                    "branch_code": branch.branch_code,
                    "display_name": branch.display_name,
                    "pharmacy_type": branch.pharmacy_type.value,
                    "scale": branch.scale.value,
                    "governorate": branch.location.governorate,
                    "city": branch.location.city,
                    "assortment_capacity_skus": branch.capacity.assortment_capacity_skus,
                    "storage_capacity_units": branch.capacity.storage_capacity_units,
                    "floor_area_m2": branch.capacity.floor_area_m2,
                    "checkout_points": branch.capacity.checkout_points,
                    "cold_chain_supported": branch.capacity.cold_chain_supported,
                    "cold_chain_capacity_units": branch.capacity.cold_chain_capacity_units,
                    "service_modes": "|".join(
                        sorted(mode.value for mode in branch.operating_profile.service_modes)
                    ),
                    "timezone": branch.operating_profile.timezone,
                }
            )

    summary_path.write_text(
        json.dumps(network.summary(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return org_path, branch_path, summary_path
