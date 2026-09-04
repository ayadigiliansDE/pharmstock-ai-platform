"""Stage 5D master-data snapshot contracts and local preparation.

This module is deliberately dependency-light apart from the existing PharmStock domain/simulation
package. Local preparation never mutates Google Cloud.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pharmstock.simulation import PharmacyNetworkGenerator, export_network

DEFAULT_MASTER_DATASET: Final[str] = "pharmstock_master"
DEFAULT_LOCATION: Final[str] = "EU"

PRODUCT_FIELDS: Final[tuple[str, ...]] = (
    "product_id",
    "display_name",
    "brand_name",
    "generic_name",
    "dosage_form",
    "routes",
    "active_ingredients",
    "package_description",
    "manufacturer",
    "prescription_status",
    "regulatory_status",
    "market_code",
    "rxnorm_rxcui",
    "ndc_product_code",
    "ndc_package_code",
    "source_system",
    "source_record_id",
    "source_updated_at",
    "source_market",
    "record_origin",
)

ORGANIZATION_FIELDS: Final[tuple[str, ...]] = (
    "organization_id",
    "organization_code",
    "legal_name",
    "display_name",
    "organization_type",
    "market_code",
    "synthetic_record",
    "record_origin",
)

BRANCH_FIELDS: Final[tuple[str, ...]] = (
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
    "synthetic_record",
    "record_origin",
)

SUPPLIER_FIELDS: Final[tuple[str, ...]] = (
    "supplier_id",
    "supplier_code",
    "display_name",
    "supplier_type",
    "market_code",
    "base_lead_time_days",
    "service_regions",
    "service_governorates",
    "catalog_coverage_pct",
    "expected_fill_rate_pct",
    "reliability_score_pct",
    "cycle_capacity_units",
    "cold_chain_supported",
    "synthetic_record",
    "record_origin",
)

MASTER_TABLES: Final[tuple[str, ...]] = (
    "product_master",
    "pharmacy_organization_master",
    "pharmacy_branch_master",
    "supplier_master",
)

MASTER_PRIMARY_KEYS: Final[dict[str, str]] = {
    "product_master": "product_id",
    "pharmacy_organization_master": "organization_id",
    "pharmacy_branch_master": "branch_id",
    "supplier_master": "supplier_id",
}

BIGQUERY_SCHEMAS: Final[dict[str, tuple[tuple[str, str, str], ...]]] = {
    "product_master": tuple(
        (field, "STRING", "REQUIRED" if field in {
            "product_id",
            "display_name",
            "dosage_form",
            "prescription_status",
            "regulatory_status",
            "market_code",
            "source_system",
            "source_record_id",
            "source_market",
            "record_origin",
        } else "NULLABLE")
        for field in PRODUCT_FIELDS
    ),
    "pharmacy_organization_master": (
        ("organization_id", "STRING", "REQUIRED"),
        ("organization_code", "STRING", "REQUIRED"),
        ("legal_name", "STRING", "REQUIRED"),
        ("display_name", "STRING", "REQUIRED"),
        ("organization_type", "STRING", "REQUIRED"),
        ("market_code", "STRING", "REQUIRED"),
        ("synthetic_record", "BOOLEAN", "REQUIRED"),
        ("record_origin", "STRING", "REQUIRED"),
    ),
    "pharmacy_branch_master": (
        ("branch_id", "STRING", "REQUIRED"),
        ("organization_id", "STRING", "REQUIRED"),
        ("branch_code", "STRING", "REQUIRED"),
        ("display_name", "STRING", "REQUIRED"),
        ("pharmacy_type", "STRING", "REQUIRED"),
        ("scale", "STRING", "REQUIRED"),
        ("governorate", "STRING", "REQUIRED"),
        ("city", "STRING", "REQUIRED"),
        ("assortment_capacity_skus", "INTEGER", "REQUIRED"),
        ("storage_capacity_units", "INTEGER", "REQUIRED"),
        ("floor_area_m2", "FLOAT", "REQUIRED"),
        ("checkout_points", "INTEGER", "REQUIRED"),
        ("cold_chain_supported", "BOOLEAN", "REQUIRED"),
        ("cold_chain_capacity_units", "INTEGER", "REQUIRED"),
        ("service_modes", "STRING", "REQUIRED"),
        ("timezone", "STRING", "REQUIRED"),
        ("synthetic_record", "BOOLEAN", "REQUIRED"),
        ("record_origin", "STRING", "REQUIRED"),
    ),
    "supplier_master": (
        ("supplier_id", "STRING", "REQUIRED"),
        ("supplier_code", "STRING", "REQUIRED"),
        ("display_name", "STRING", "REQUIRED"),
        ("supplier_type", "STRING", "REQUIRED"),
        ("market_code", "STRING", "REQUIRED"),
        ("base_lead_time_days", "INTEGER", "REQUIRED"),
        ("service_regions", "STRING", "REQUIRED"),
        ("service_governorates", "STRING", "REQUIRED"),
        ("catalog_coverage_pct", "FLOAT", "REQUIRED"),
        ("expected_fill_rate_pct", "FLOAT", "REQUIRED"),
        ("reliability_score_pct", "FLOAT", "REQUIRED"),
        ("cycle_capacity_units", "INTEGER", "REQUIRED"),
        ("cold_chain_supported", "BOOLEAN", "REQUIRED"),
        ("synthetic_record", "BOOLEAN", "REQUIRED"),
        ("record_origin", "STRING", "REQUIRED"),
    ),
}

BIGQUERY_CLUSTER_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "product_master": ("dosage_form", "prescription_status", "manufacturer"),
    "pharmacy_organization_master": ("organization_type", "market_code"),
    "pharmacy_branch_master": ("governorate", "scale", "pharmacy_type"),
    "supplier_master": ("supplier_type", "market_code"),
}


@dataclass(frozen=True, slots=True)
class MasterStage5DConfig:
    project_id: str | None
    master_dataset: str
    location: str

    @property
    def project_configured(self) -> bool:
        return bool(self.project_id and self.project_id.strip())


@dataclass(frozen=True, slots=True)
class MasterStage5DReadiness:
    catalog_path: str
    inventory_manifest_path: str
    supplier_master_path: str
    stage5c_cloud_report_present: bool
    product_rows: int
    organization_rows: int
    branch_rows: int
    supplier_rows: int
    local_ready: bool
    issues: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "catalog_path": self.catalog_path,
            "inventory_manifest_path": self.inventory_manifest_path,
            "supplier_master_path": self.supplier_master_path,
            "stage5c_cloud_report_present": self.stage5c_cloud_report_present,
            "product_rows": self.product_rows,
            "organization_rows": self.organization_rows,
            "branch_rows": self.branch_rows,
            "supplier_rows": self.supplier_rows,
            "local_ready": self.local_ready,
            "issues": list(self.issues),
        }


def config_from_environment() -> MasterStage5DConfig:
    project = os.getenv("PHARMSTOCK_BQ_PROJECT", "").strip() or None
    dataset = os.getenv("PHARMSTOCK_BQ_MASTER_DATASET", DEFAULT_MASTER_DATASET).strip()
    location = os.getenv("PHARMSTOCK_BQ_LOCATION", DEFAULT_LOCATION).strip()
    return MasterStage5DConfig(project, dataset, location)


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _row_count(path: Path) -> int:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        return sum(1 for _ in reader)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_catalog_csv(expected_active_rows: int) -> Path:
    candidates = (
        Path("artifacts/stage2b-5000"),
        Path("artifacts/stage2b"),
        Path("artifacts/stage2b-1000"),
    )
    available: list[Path] = []
    diagnostics: list[str] = []
    for directory in candidates:
        csv_path = directory / "drug_catalog.csv"
        json_path = directory / "drug_catalog.json"
        if not csv_path.is_file():
            continue
        available.append(csv_path)
        if json_path.is_file():
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            active_rows = sum(
                1
                for item in payload
                if str(item.get("regulatory_status", "")).lower() == "active"
            )
            diagnostics.append(f"{csv_path}=active:{active_rows},all:{len(payload)}")
            if active_rows == expected_active_rows:
                return csv_path
        else:
            rows = _row_count(csv_path)
            diagnostics.append(f"{csv_path}=all:{rows}")
            if rows == expected_active_rows:
                return csv_path
    if not available:
        raise FileNotFoundError("Stage 2B drug_catalog.csv was not found")
    raise RuntimeError(
        "No Stage 2B catalog matches Stage 2D active product count "
        f"{expected_active_rows}: {', '.join(diagnostics)}"
    )


def _write_rows(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _validate_unique(rows: list[dict[str, object]], key: str, table: str) -> None:
    values = [str(row.get(key, "")).strip() for row in rows]
    if any(not value for value in values):
        raise RuntimeError(f"{table}.{key} contains blank values")
    if len(values) != len(set(values)):
        raise RuntimeError(f"{table}.{key} is not unique")


def _normalize_products(source: Path, target: Path) -> int:
    rows = _csv_rows(source)
    normalized: list[dict[str, object]] = []
    for row in rows:
        item: dict[str, object] = dict(row)
        item["source_market"] = "US"
        item["record_origin"] = "official_openfda_ndc"
        normalized.append(item)
    _validate_unique(normalized, "product_id", "product_master")
    forbidden = {"price", "revenue", "cost", "margin", "unit_price", "unit_cost"}
    if forbidden.intersection({name.lower() for name in normalized[0]} if normalized else set()):
        raise RuntimeError("product master unexpectedly contains monetary fields")
    _write_rows(target, PRODUCT_FIELDS, normalized)
    return len(normalized)


def _normalize_network(
    *, manifest: dict[str, object], output_root: Path
) -> tuple[int, int]:
    seed = int(manifest["seed"])
    branch_count = int(manifest["branch_count"])
    network = PharmacyNetworkGenerator(seed=seed).generate(branch_count)
    temp = output_root / "_network_source"
    if temp.exists():
        shutil.rmtree(temp)
    org_path, branch_path, _ = export_network(network, temp)
    org_rows = _csv_rows(org_path)
    branch_rows = _csv_rows(branch_path)

    normalized_orgs: list[dict[str, object]] = []
    for row in org_rows:
        item: dict[str, object] = dict(row)
        item["synthetic_record"] = True
        item["record_origin"] = "synthetic_egypt_pharmacy_network"
        normalized_orgs.append(item)
    normalized_branches: list[dict[str, object]] = []
    for row in branch_rows:
        item = dict(row)
        item["synthetic_record"] = True
        item["record_origin"] = "synthetic_egypt_pharmacy_network"
        normalized_branches.append(item)

    _validate_unique(normalized_orgs, "organization_id", "pharmacy_organization_master")
    _validate_unique(normalized_branches, "branch_id", "pharmacy_branch_master")
    org_ids = {str(row["organization_id"]) for row in normalized_orgs}
    orphaned = [
        str(row["branch_id"])
        for row in normalized_branches
        if str(row["organization_id"]) not in org_ids
    ]
    if orphaned:
        raise RuntimeError(f"branch master contains orphan organization IDs: {orphaned[:3]}")

    _write_rows(
        output_root / "master_ready/pharmacy_organization_master.csv",
        ORGANIZATION_FIELDS,
        normalized_orgs,
    )
    _write_rows(
        output_root / "master_ready/pharmacy_branch_master.csv",
        BRANCH_FIELDS,
        normalized_branches,
    )
    shutil.rmtree(temp)
    return len(normalized_orgs), len(normalized_branches)


def _normalize_suppliers(source: Path, target: Path) -> int:
    rows = _csv_rows(source)
    normalized: list[dict[str, object]] = []
    for row in rows:
        synthetic = str(row.get("synthetic_record", "")).strip().lower()
        if synthetic not in {"true", "1", "yes"}:
            raise RuntimeError("Stage 5D supplier master must remain explicitly synthetic")
        item: dict[str, object] = dict(row)
        item["record_origin"] = "synthetic_supplier_network"
        normalized.append(item)
    _validate_unique(normalized, "supplier_id", "supplier_master")
    _write_rows(target, SUPPLIER_FIELDS, normalized)
    return len(normalized)


def _write_contracts(output_root: Path) -> None:
    contracts = output_root / "contracts"
    contracts.mkdir(parents=True, exist_ok=True)
    for table in MASTER_TABLES:
        payload = {
            "table": table,
            "primary_key": MASTER_PRIMARY_KEYS[table],
            "schema": [
                {"name": name, "type": field_type, "mode": mode}
                for name, field_type, mode in BIGQUERY_SCHEMAS[table]
            ],
            "clustering_fields": list(BIGQUERY_CLUSTER_FIELDS[table]),
        }
        (contracts / f"{table}.schema.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )


def prepare_master_snapshot(
    output_root: Path = Path("artifacts/stage5d"),
) -> dict[str, object]:
    inventory_manifest_path = Path("artifacts/stage2d/inventory_manifest.json")
    supplier_master_path = Path("artifacts/stage2f1/supplier_master.csv")
    stage5c_report_path = Path("artifacts/stage5c/cloud_execution_report.json")
    if not Path("artifacts/stage2d/_SUCCESS").is_file():
        raise RuntimeError("Completed Stage 2D checkpoint is required")
    if not inventory_manifest_path.is_file():
        raise RuntimeError("Stage 2D inventory_manifest.json is required")
    if not Path("artifacts/stage2f1/_SUCCESS").is_file() or not supplier_master_path.is_file():
        raise RuntimeError("Completed Stage 2F.1 supplier master is required")
    if not stage5c_report_path.is_file():
        raise RuntimeError("Stage 5C cloud_execution_report.json is required")

    stage5c_report = json.loads(stage5c_report_path.read_text(encoding="utf-8"))
    if stage5c_report.get("cloud_mutation") is not True:
        raise RuntimeError("Stage 5C cloud execution report is not successful")

    manifest = json.loads(inventory_manifest_path.read_text(encoding="utf-8"))
    expected_products = int(manifest["catalog_products_available"])
    catalog_path = _find_catalog_csv(expected_products)

    if output_root.exists():
        shutil.rmtree(output_root)
    (output_root / "master_ready").mkdir(parents=True, exist_ok=True)

    product_target = output_root / "master_ready/product_master.csv"
    supplier_target = output_root / "master_ready/supplier_master.csv"
    product_rows = _normalize_products(catalog_path, product_target)
    organization_rows, branch_rows = _normalize_network(
        manifest=manifest,
        output_root=output_root,
    )
    supplier_rows = _normalize_suppliers(supplier_master_path, supplier_target)
    _write_contracts(output_root)

    files = {
        table: output_root / "master_ready" / f"{table}.csv" for table in MASTER_TABLES
    }
    table_counts = {
        "product_master": product_rows,
        "pharmacy_organization_master": organization_rows,
        "pharmacy_branch_master": branch_rows,
        "supplier_master": supplier_rows,
    }
    source_lineage = {
        "product_master": {
            "source_stage": "2B",
            "source_file": str(catalog_path),
            "source_market": "US",
            "record_origin": "official_openfda_ndc",
        },
        "pharmacy_organization_master": {
            "source_stage": "2D",
            "source_file": str(inventory_manifest_path),
            "simulation_market": "EG",
            "record_origin": "synthetic_egypt_pharmacy_network",
        },
        "pharmacy_branch_master": {
            "source_stage": "2D",
            "source_file": str(inventory_manifest_path),
            "simulation_market": "EG",
            "record_origin": "synthetic_egypt_pharmacy_network",
        },
        "supplier_master": {
            "source_stage": "2F.1",
            "source_file": str(supplier_master_path),
            "record_origin": "synthetic_supplier_network",
        },
    }
    snapshot_id = hashlib.sha256(
        "|".join(f"{table}:{_sha256(files[table])}" for table in MASTER_TABLES).encode()
    ).hexdigest()
    readiness = MasterStage5DReadiness(
        catalog_path=str(catalog_path),
        inventory_manifest_path=str(inventory_manifest_path),
        supplier_master_path=str(supplier_master_path),
        stage5c_cloud_report_present=True,
        product_rows=product_rows,
        organization_rows=organization_rows,
        branch_rows=branch_rows,
        supplier_rows=supplier_rows,
        local_ready=True,
        issues=(),
    )
    config = config_from_environment()
    report = {
        "stage": "5D",
        "mode": "local_master_snapshot",
        "generated_at": datetime.now(UTC).isoformat(),
        "cloud_mutation": False,
        "snapshot_id": snapshot_id,
        "project_id": config.project_id,
        "master_dataset": config.master_dataset,
        "location": config.location,
        "table_counts": table_counts,
        "total_master_rows": sum(table_counts.values()),
        "source_lineage": source_lineage,
        "readiness": readiness.to_dict(),
        "monetary_measures_generated": False,
    }
    (output_root / "master_snapshot_manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output_root / "local_verification.json").write_text(
        json.dumps(readiness.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
    )
    (output_root / "_SUCCESS").write_text("STAGE_5D_STATUS=PASS\n", encoding="utf-8")
    return report


__all__ = [
    "BIGQUERY_CLUSTER_FIELDS",
    "BIGQUERY_SCHEMAS",
    "DEFAULT_LOCATION",
    "DEFAULT_MASTER_DATASET",
    "MASTER_PRIMARY_KEYS",
    "MASTER_TABLES",
    "MasterStage5DConfig",
    "MasterStage5DReadiness",
    "config_from_environment",
    "prepare_master_snapshot",
]
