"""Production-like Egyptian pharmacy network calibrated to public 2024 statistics.

The generated organizations and branches are fictional. CAPMAS population and
urban/rural estimates plus the national count of general pharmacies are used only
as calibration anchors. No generated branch represents a real licensed pharmacy.
"""

from __future__ import annotations

import csv
import json
import math
import random
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid5

from pharmstock.simulation.geography import (
    CAPMAS_POPULATION_2024_TOTAL,
    EGYPT_GOVERNORATES,
    GovernorateProfile,
    validate_governorate_reference,
)

CAPMAS_GENERAL_PHARMACIES_2024 = 86_741
CAPMAS_PHARMACY_DENSITY_PER_1000 = (
    CAPMAS_GENERAL_PHARMACIES_2024 / CAPMAS_POPULATION_2024_TOTAL * 1_000
)

POPULATION_REFERENCE_URL = (
    "https://www.capmas.gov.eg/Admin/Pages%20Files/20245121324361-%20pop_new.pdf"
)
PHARMACY_REFERENCE_URL = (
    "https://censusinfo.capmas.gov.eg/Metadata-Ar-v4.2/index.php/"
    "catalog/1944/download/7026"
)
EDA_LICENSING_REFERENCE_URL = (
    "https://edaegypt.gov.eg/en/publications-reports-and-eda-in-numbers/"
    "eda-in-numbers/pharmaceutical-institutions-licensing/"
)

_NETWORK_NAMESPACE = UUID("0ccb3b55-48e8-4bc0-91a4-806ecad7b4fa")


class ProductionNetworkProfile(StrEnum):
    DEV = "dev"
    ACCEPTANCE = "acceptance"
    FULL_MARKET = "full_market"


PROFILE_BRANCH_COUNTS: dict[ProductionNetworkProfile, int] = {
    ProductionNetworkProfile.DEV: 27,
    ProductionNetworkProfile.ACCEPTANCE: 5_000,
    ProductionNetworkProfile.FULL_MARKET: CAPMAS_GENERAL_PHARMACIES_2024,
}


@dataclass(frozen=True, slots=True)
class OwnershipMix:
    """Synthetic branch-level ownership assumptions, not official market shares."""

    independent: float = 0.70
    chain: float = 0.24
    hospital_network: float = 0.04
    digital_operator: float = 0.02

    def items(self) -> tuple[tuple[str, float], ...]:
        values = (
            ("independent", self.independent),
            ("chain", self.chain),
            ("hospital_network", self.hospital_network),
            ("digital_operator", self.digital_operator),
        )
        if not math.isclose(sum(value for _, value in values), 1.0, abs_tol=1e-9):
            raise ValueError("ownership branch shares must sum to 1.0")
        if any(value < 0 for _, value in values):
            raise ValueError("ownership branch shares cannot be negative")
        return values


@dataclass(frozen=True, slots=True)
class ProductionOrganizationRow:
    organization_id: str
    organization_code: str
    display_name: str
    organization_type: str
    planned_branch_count: int
    market_code: str = "EG"
    provenance_class: str = "SYNTHETIC_CALIBRATED"
    synthetic_record: bool = True


@dataclass(frozen=True, slots=True)
class ProductionBranchRow:
    branch_id: str
    organization_id: str
    branch_code: str
    display_name: str
    governorate_code: str
    governorate: str
    representative_city: str
    locality_type: str
    locality_code: str
    organization_type: str
    pharmacy_type: str
    scale: str
    is_24_hours: bool
    service_modes: str
    assortment_capacity_skus: int
    storage_capacity_units: int
    checkout_points: int
    cold_chain_supported: bool
    demand_index: float
    governorate_population_2024: int
    governorate_urban_share_2024: float
    branch_expansion_weight: float
    market_code: str = "EG"
    timezone: str = "Africa/Cairo"
    provenance_class: str = "SYNTHETIC_CALIBRATED"
    synthetic_record: bool = True


@dataclass(frozen=True, slots=True)
class GovernorateCalibrationRow:
    governorate_code: str
    governorate: str
    population_2024: int
    urban_share_2024: float
    national_population_share: float
    modeled_branch_count: int
    modeled_branch_share: float
    modeled_full_market_pharmacies: int
    calibration_basis: str = "CAPMAS_2024_POPULATION_PROPORTIONAL"


@dataclass(frozen=True, slots=True)
class ProductionNetworkResult:
    profile: ProductionNetworkProfile
    seed: int
    branch_count: int
    organizations: tuple[ProductionOrganizationRow, ...]
    branches: tuple[ProductionBranchRow, ...]
    governorate_calibration: tuple[GovernorateCalibrationRow, ...]

    @property
    def market_coverage_ratio(self) -> float:
        return self.branch_count / CAPMAS_GENERAL_PHARMACIES_2024

    @property
    def branch_expansion_weight(self) -> float:
        return CAPMAS_GENERAL_PHARMACIES_2024 / self.branch_count

    def summary(self) -> dict[str, object]:
        branch_governorates = Counter(row.governorate for row in self.branches)
        localities = Counter(row.locality_type for row in self.branches)
        ownership = Counter(row.organization_type for row in self.branches)
        scales = Counter(row.scale for row in self.branches)
        return {
            "profile": self.profile.value,
            "seed": self.seed,
            "branch_count": self.branch_count,
            "organization_count": len(self.organizations),
            "governorate_count": len(branch_governorates),
            "urban_branch_count": localities["urban"],
            "rural_branch_count": localities["rural"],
            "market_coverage_ratio": self.market_coverage_ratio,
            "branch_expansion_weight": self.branch_expansion_weight,
            "capmas_population_2024": CAPMAS_POPULATION_2024_TOTAL,
            "capmas_general_pharmacies_2024": CAPMAS_GENERAL_PHARMACIES_2024,
            "capmas_pharmacy_density_per_1000": CAPMAS_PHARMACY_DENSITY_PER_1000,
            "branches_by_governorate": dict(sorted(branch_governorates.items())),
            "branches_by_locality_type": dict(sorted(localities.items())),
            "branches_by_ownership": dict(sorted(ownership.items())),
            "branches_by_scale": dict(sorted(scales.items())),
            "provenance_class": "SYNTHETIC_CALIBRATED",
            "real_branch_identities_used": False,
        }


class ProductionPharmacyNetworkGenerator:
    """Create a deterministic high-fidelity pharmacy-market digital twin."""

    def __init__(
        self,
        *,
        seed: int = 20260823,
        ownership_mix: OwnershipMix | None = None,
    ) -> None:
        validate_governorate_reference()
        self.seed = seed
        self.ownership_mix = ownership_mix or OwnershipMix()
        self.ownership_mix.items()
        self._rng = random.Random(seed)

    def generate(
        self,
        *,
        profile: ProductionNetworkProfile = ProductionNetworkProfile.ACCEPTANCE,
        branch_count: int | None = None,
    ) -> ProductionNetworkResult:
        count = branch_count if branch_count is not None else PROFILE_BRANCH_COUNTS[profile]
        if count < len(EGYPT_GOVERNORATES):
            raise ValueError("production network must cover all 27 governorates")
        if count > 1_000_000:
            raise ValueError("branch_count safety limit is 1,000,000")

        governorate_counts = _largest_remainder_allocation(
            count,
            {item.code: item.population_2024 for item in EGYPT_GOVERNORATES},
            minimum_each=1,
        )
        full_market_counts = _largest_remainder_allocation(
            CAPMAS_GENERAL_PHARMACIES_2024,
            {item.code: item.population_2024 for item in EGYPT_GOVERNORATES},
            minimum_each=1,
        )
        ownership_counts = _largest_remainder_allocation(
            count,
            dict(self.ownership_mix.items()),
        )
        organizations, organization_slots = self._organizations(ownership_counts)
        branches = self._branches(
            governorate_counts=governorate_counts,
            organization_slots=organization_slots,
            branch_expansion_weight=CAPMAS_GENERAL_PHARMACIES_2024 / count,
        )
        calibration = self._calibration(
            governorate_counts=governorate_counts,
            full_market_counts=full_market_counts,
            branch_count=count,
        )
        return ProductionNetworkResult(
            profile=profile,
            seed=self.seed,
            branch_count=count,
            organizations=tuple(organizations),
            branches=tuple(branches),
            governorate_calibration=tuple(calibration),
        )

    def _organizations(
        self,
        ownership_counts: dict[str, int],
    ) -> tuple[list[ProductionOrganizationRow], list[ProductionOrganizationRow]]:
        organizations: list[ProductionOrganizationRow] = []
        slots: list[ProductionOrganizationRow] = []
        counters: Counter[str] = Counter()
        for ownership, branch_quota in ownership_counts.items():
            remaining = branch_quota
            while remaining > 0:
                counters[ownership] += 1
                if ownership == "independent":
                    planned = 1
                elif ownership == "chain":
                    planned = min(remaining, self._rng.randint(8, 80))
                elif ownership == "hospital_network":
                    planned = min(remaining, self._rng.randint(2, 15))
                else:
                    planned = min(remaining, self._rng.randint(4, 30))
                code = f"SIM-{ownership[:3].upper()}-{counters[ownership]:05d}"
                organization_id = str(
                    uuid5(_NETWORK_NAMESPACE, f"seed={self.seed}|organization={code}")
                )
                row = ProductionOrganizationRow(
                    organization_id=organization_id,
                    organization_code=code,
                    display_name=(
                        f"Synthetic {ownership.replace('_', ' ').title()} "
                        f"{counters[ownership]:05d}"
                    ),
                    organization_type=ownership,
                    planned_branch_count=planned,
                )
                organizations.append(row)
                slots.extend([row] * planned)
                remaining -= planned
        self._rng.shuffle(slots)
        return organizations, slots

    def _branches(
        self,
        *,
        governorate_counts: dict[str, int],
        organization_slots: list[ProductionOrganizationRow],
        branch_expansion_weight: float,
    ) -> list[ProductionBranchRow]:
        profile_by_code = {item.code: item for item in EGYPT_GOVERNORATES}
        governorate_slots: list[GovernorateProfile] = []
        for code, count in governorate_counts.items():
            governorate_slots.extend([profile_by_code[code]] * count)
        self._rng.shuffle(governorate_slots)
        if len(governorate_slots) != len(organization_slots):
            raise RuntimeError("governorate and organization allocations do not reconcile")

        branches: list[ProductionBranchRow] = []
        locality_counters: Counter[tuple[str, str]] = Counter()
        for index, (governorate, organization) in enumerate(
            zip(governorate_slots, organization_slots, strict=True),
            start=1,
        ):
            locality_type = (
                "urban"
                if self._rng.random() < governorate.urban_share_2024
                else "rural"
            )
            locality_key = (governorate.code, locality_type)
            locality_counters[locality_key] += 1
            locality_code = (
                f"{governorate.code}-{locality_type[:1].upper()}-"
                f"{locality_counters[locality_key]:05d}"
            )
            scale = self._choose_scale(
                ownership=organization.organization_type,
                locality_type=locality_type,
            )
            pharmacy_type = self._pharmacy_type(organization.organization_type)
            is_24_hours = self._is_24_hours(
                pharmacy_type=pharmacy_type,
                scale=scale,
                locality_type=locality_type,
            )
            capacities = self._capacities(scale)
            branch_code = f"{governorate.code}-PDT-{index:06d}"
            branch_id = str(
                uuid5(
                    _NETWORK_NAMESPACE,
                    (
                        f"seed={self.seed}|branch={branch_code}|"
                        f"organization={organization.organization_code}"
                    ),
                )
            )
            branches.append(
                ProductionBranchRow(
                    branch_id=branch_id,
                    organization_id=organization.organization_id,
                    branch_code=branch_code,
                    display_name=f"Synthetic Pharmacy {branch_code}",
                    governorate_code=governorate.code,
                    governorate=governorate.name_en,
                    representative_city=governorate.representative_city,
                    locality_type=locality_type,
                    locality_code=locality_code,
                    organization_type=organization.organization_type,
                    pharmacy_type=pharmacy_type,
                    scale=scale,
                    is_24_hours=is_24_hours,
                    service_modes=self._service_modes(
                        pharmacy_type=pharmacy_type,
                        scale=scale,
                        locality_type=locality_type,
                    ),
                    assortment_capacity_skus=capacities[0],
                    storage_capacity_units=capacities[1],
                    checkout_points=capacities[2],
                    cold_chain_supported=capacities[3],
                    demand_index=self._demand_index(
                        governorate=governorate,
                        locality_type=locality_type,
                        scale=scale,
                    ),
                    governorate_population_2024=governorate.population_2024,
                    governorate_urban_share_2024=governorate.urban_share_2024,
                    branch_expansion_weight=branch_expansion_weight,
                )
            )
        return branches

    def _calibration(
        self,
        *,
        governorate_counts: dict[str, int],
        full_market_counts: dict[str, int],
        branch_count: int,
    ) -> list[GovernorateCalibrationRow]:
        rows: list[GovernorateCalibrationRow] = []
        for item in EGYPT_GOVERNORATES:
            modeled = governorate_counts[item.code]
            rows.append(
                GovernorateCalibrationRow(
                    governorate_code=item.code,
                    governorate=item.name_en,
                    population_2024=item.population_2024,
                    urban_share_2024=item.urban_share_2024,
                    national_population_share=(
                        item.population_2024 / CAPMAS_POPULATION_2024_TOTAL
                    ),
                    modeled_branch_count=modeled,
                    modeled_branch_share=modeled / branch_count,
                    modeled_full_market_pharmacies=full_market_counts[item.code],
                )
            )
        return rows

    def _choose_scale(self, *, ownership: str, locality_type: str) -> str:
        if ownership == "chain":
            values = ["small", "medium", "large", "flagship"]
            weights = [0.12, 0.51, 0.31, 0.06]
        elif ownership == "hospital_network":
            values = ["medium", "large", "flagship"]
            weights = [0.22, 0.58, 0.20]
        elif ownership == "digital_operator":
            values = ["medium", "large", "flagship"]
            weights = [0.10, 0.55, 0.35]
        elif locality_type == "rural":
            values = ["small", "medium", "large"]
            weights = [0.72, 0.25, 0.03]
        else:
            values = ["small", "medium", "large", "flagship"]
            weights = [0.48, 0.40, 0.10, 0.02]
        return self._rng.choices(values, weights=weights, k=1)[0]

    @staticmethod
    def _pharmacy_type(ownership: str) -> str:
        if ownership == "hospital_network":
            return "hospital"
        if ownership == "digital_operator":
            return "fulfillment_center"
        return "community"

    def _is_24_hours(self, *, pharmacy_type: str, scale: str, locality_type: str) -> bool:
        if pharmacy_type == "hospital":
            return self._rng.random() < 0.85
        if pharmacy_type == "fulfillment_center":
            return self._rng.random() < 0.65
        probability = 0.03 if locality_type == "rural" else 0.10
        if scale in {"large", "flagship"}:
            probability += 0.20
        return self._rng.random() < probability

    def _capacities(self, scale: str) -> tuple[int, int, int, bool]:
        ranges = {
            "small": ((900, 2_800), (8_000, 28_000), (1, 2), 0.68),
            "medium": ((2_500, 6_500), (22_000, 75_000), (2, 5), 0.88),
            "large": ((6_000, 13_000), (65_000, 190_000), (4, 10), 0.97),
            "flagship": ((12_000, 20_000), (150_000, 450_000), (8, 24), 0.995),
        }
        sku_range, unit_range, checkout_range, cold_probability = ranges[scale]
        return (
            self._rng.randint(*sku_range),
            self._rng.randint(*unit_range),
            self._rng.randint(*checkout_range),
            self._rng.random() < cold_probability,
        )

    def _service_modes(self, *, pharmacy_type: str, scale: str, locality_type: str) -> str:
        if pharmacy_type == "fulfillment_center":
            return "delivery|online_fulfillment"
        modes = {"in_store"}
        delivery_probability = 0.35 if locality_type == "rural" else 0.68
        if self._rng.random() < delivery_probability:
            modes.add("delivery")
        if scale in {"large", "flagship"}:
            modes.add("click_and_collect")
        return "|".join(sorted(modes))

    def _demand_index(
        self,
        *,
        governorate: GovernorateProfile,
        locality_type: str,
        scale: str,
    ) -> float:
        locality_factor = 1.12 if locality_type == "urban" else 0.82
        scale_factor = {
            "small": 0.72,
            "medium": 1.00,
            "large": 1.48,
            "flagship": 2.10,
        }[scale]
        population_factor = min(
            1.20,
            max(0.90, governorate.population_2024 / 5_000_000),
        )
        noise = self._rng.uniform(0.92, 1.08)
        return round(locality_factor * scale_factor * population_factor * noise, 4)


def _largest_remainder_allocation(
    total: int,
    weights: dict[str, float | int],
    *,
    minimum_each: int = 0,
) -> dict[str, int]:
    if total <= 0:
        raise ValueError("allocation total must be positive")
    if not weights or any(value < 0 for value in weights.values()):
        raise ValueError("allocation weights must be non-empty and non-negative")
    if total < minimum_each * len(weights):
        raise ValueError("allocation total cannot satisfy minimum_each")

    allocation = {key: minimum_each for key in weights}
    remaining_total = total - minimum_each * len(weights)
    weight_total = float(sum(weights.values()))
    if weight_total <= 0:
        raise ValueError("allocation weights must have a positive sum")

    raw = {
        key: remaining_total * float(value) / weight_total
        for key, value in weights.items()
    }
    floors = {key: math.floor(value) for key, value in raw.items()}
    for key, value in floors.items():
        allocation[key] += value
    remaining = total - sum(allocation.values())
    ranked = sorted(
        weights,
        key=lambda key: (raw[key] - floors[key], key),
        reverse=True,
    )
    for key in ranked[:remaining]:
        allocation[key] += 1
    return allocation


def export_production_network(
    result: ProductionNetworkResult,
    output_dir: str | Path,
) -> dict[str, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    paths = {
        "organizations": target / "production_pharmacy_organizations.csv",
        "branches": target / "production_pharmacy_branches.csv",
        "calibration": target / "governorate_calibration.csv",
        "summary": target / "network_summary.json",
        "quality": target / "network_quality_report.json",
        "references": target / "calibration_references.json",
        "success": target / "_SUCCESS",
    }
    _write_dataclass_csv(paths["organizations"], result.organizations)
    _write_dataclass_csv(paths["branches"], result.branches)
    _write_dataclass_csv(paths["calibration"], result.governorate_calibration)

    summary = result.summary()
    paths["summary"].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    quality = _quality_report(result)
    paths["quality"].write_text(
        json.dumps(quality, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    references = {
        "population_reference": {
            "publisher": "CAPMAS",
            "reference_date": "2024-01-01",
            "population": CAPMAS_POPULATION_2024_TOTAL,
            "url": POPULATION_REFERENCE_URL,
        },
        "pharmacy_count_reference": {
            "publisher": "CAPMAS",
            "reference_year": 2024,
            "general_pharmacies": CAPMAS_GENERAL_PHARMACIES_2024,
            "url": PHARMACY_REFERENCE_URL,
        },
        "eda_cross_reference": {
            "publisher": "Egyptian Drug Authority",
            "reference_year": 2024,
            "url": EDA_LICENSING_REFERENCE_URL,
        },
        "important_note": (
            "Only national and governorate demographic statistics are public anchors. "
            "All generated branch identities, ownership and operating attributes are "
            "SYNTHETIC_CALIBRATED and must not be represented as licensed pharmacies."
        ),
    }
    paths["references"].write_text(
        json.dumps(references, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    paths["success"].write_text("STAGE_7B_STATUS=PASS\n", encoding="utf-8")
    return paths


def _write_dataclass_csv(path: Path, rows: Iterable[object]) -> None:
    rows = tuple(rows)
    if not rows:
        raise ValueError(f"cannot export empty dataset: {path.name}")
    dictionaries = [asdict(row) for row in rows]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(dictionaries[0]))
        writer.writeheader()
        writer.writerows(dictionaries)


def _quality_report(result: ProductionNetworkResult) -> dict[str, object]:
    branch_ids = {row.branch_id for row in result.branches}
    branch_codes = {row.branch_code for row in result.branches}
    organization_ids = {row.organization_id for row in result.organizations}
    branch_organization_ids = {row.organization_id for row in result.branches}
    synthetic_rows = sum(row.synthetic_record for row in result.branches)
    governorate_count = len({row.governorate_code for row in result.branches})
    calibration_total = sum(row.modeled_branch_count for row in result.governorate_calibration)
    full_market_total = sum(
        row.modeled_full_market_pharmacies for row in result.governorate_calibration
    )
    checks = {
        "branch_id_unique": len(branch_ids) == result.branch_count,
        "branch_code_unique": len(branch_codes) == result.branch_count,
        "organization_fk_valid": branch_organization_ids <= organization_ids,
        "all_27_governorates_present": governorate_count == 27,
        "all_branches_synthetic_calibrated": synthetic_rows == result.branch_count,
        "governorate_allocation_reconciles": calibration_total == result.branch_count,
        "full_market_reference_reconciles": (
            full_market_total == CAPMAS_GENERAL_PHARMACIES_2024
        ),
    }
    if not all(checks.values()):
        raise RuntimeError(f"production network quality checks failed: {checks}")
    return {
        "status": "PASS",
        "checks": checks,
        "branch_count": result.branch_count,
        "organization_count": len(result.organizations),
        "governorate_count": governorate_count,
        "provenance_class": "SYNTHETIC_CALIBRATED",
        "cloud_mutation_performed": False,
    }
