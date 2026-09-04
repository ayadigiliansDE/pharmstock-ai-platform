"""Dependency-light contracts for the Stage 7D on-prem PostgreSQL platform."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

POSTGRES_IMAGE: Final[str] = "postgres:18.6"
POSTGRES_MAJOR_VERSION: Final[int] = 18
POSTGRES_DATABASE: Final[str] = "pharmstock_ops"
POSTGRES_ADMIN_USER: Final[str] = "pharmstock_admin"
POSTGRES_APP_USER: Final[str] = "pharmstock_app"
POSTGRES_CDC_USER: Final[str] = "pharmstock_cdc"
POSTGRES_HOST_PORT: Final[int] = 5433
CDC_PUBLICATION: Final[str] = "pharmstock_cdc_publication"
CDC_SLOT: Final[str] = "pharmstock_cdc_slot"
CDC_PLUGIN: Final[str] = "pgoutput"
CDC_TOPIC_PREFIX: Final[str] = "pharmstock.ops"
DEBEZIUM_COMPATIBLE_RELEASE: Final[str] = "3.6.1.Final"

ONPREM_SCHEMAS: Final[tuple[str, ...]] = (
    "audit",
    "commercial",
    "inventory",
    "master",
    "pos",
    "procurement",
    "staging",
)

CDC_STAGE7D_TABLES: Final[tuple[str, ...]] = (
    "pos.sale_header",
    "pos.sale_line",
    "pos.payment",
    "pos.return_header",
    "pos.return_line",
    "inventory.stock_batch",
    "inventory.inventory_position",
    "inventory.stock_movement",
    "procurement.supplier",
    "procurement.purchase_order",
    "procurement.purchase_order_line",
    "procurement.goods_receipt",
    "procurement.goods_receipt_line",
)

# pos.demand_attempt is created by Stage 7E after the Stage 7D publication exists.
# Stage 7F+ extends the publication with this table so live ML sees lost demand
# and stockout attempts, not only fulfilled sale lines.
CDC_POST_STAGE7E_TABLES: Final[tuple[str, ...]] = ("pos.demand_attempt",)
CDC_TABLES: Final[tuple[str, ...]] = CDC_STAGE7D_TABLES + CDC_POST_STAGE7E_TABLES


@dataclass(frozen=True, slots=True)
class SeedContract:
    artifact: str
    target_table: str
    primary_key: str
    provenance_rule: str


SEED_CONTRACTS: Final[tuple[SeedContract, ...]] = (
    SeedContract(
        "artifacts/stage7a/egypt_product_master.csv",
        "master.product",
        "product_id",
        "PUBLIC_MARKET_EGYPT",
    ),
    SeedContract(
        "artifacts/stage7a/product_price_history.csv",
        "master.product_price_history",
        "price_observation_id",
        "PUBLIC_MARKET_EGYPT",
    ),
    SeedContract(
        "artifacts/stage7b/production_pharmacy_organizations.csv",
        "master.pharmacy_organization",
        "organization_id",
        "SYNTHETIC_CALIBRATED",
    ),
    SeedContract(
        "artifacts/stage7b/production_pharmacy_branches.csv",
        "master.pharmacy_branch",
        "branch_id",
        "SYNTHETIC_CALIBRATED",
    ),
    SeedContract(
        "artifacts/stage7c/product_unit_economics.csv",
        "commercial.product_unit_economics",
        "product_id",
        "MIXED_OBSERVED_AND_SYNTHETIC_CALIBRATED",
    ),
    SeedContract(
        "artifacts/stage7c/branch_commercial_policy.csv",
        "commercial.branch_commercial_policy",
        "branch_id",
        "SYNTHETIC_CALIBRATED",
    ),
)

EXPECTED_STAGE_SUCCESS: Final[tuple[str, ...]] = (
    "artifacts/stage7a/_SUCCESS",
    "artifacts/stage7b/_SUCCESS",
    "artifacts/stage7c/_SUCCESS",
)


class OnPremContractError(RuntimeError):
    """Raised when the local operational database contract cannot be satisfied."""


def input_row_counts(root: Path = Path(".")) -> dict[str, int]:
    """Count Stage 7A/B/C CSV rows without loading whole files into memory."""

    counts: dict[str, int] = {}
    for contract in SEED_CONTRACTS:
        path = root / contract.artifact
        if not path.is_file():
            raise OnPremContractError(f"required Stage 7D input is missing: {path}")
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            try:
                next(reader)
            except StopIteration as exc:
                raise OnPremContractError(f"required input is empty: {path}") from exc
            counts[contract.target_table] = sum(1 for _ in reader)
    return counts


def assert_stage_success(root: Path = Path(".")) -> None:
    missing = [path for path in EXPECTED_STAGE_SUCCESS if not (root / path).is_file()]
    if missing:
        raise OnPremContractError(
            "Stage 7D requires successful Stage 7A/7B/7C artifacts: " + ", ".join(missing)
        )


def database_contract() -> dict[str, object]:
    return {
        "stage": "7D",
        "database_role": "ON_PREM_OPERATIONAL_POS_SOURCE_OF_RECORD",
        "postgres": {
            "image": POSTGRES_IMAGE,
            "database": POSTGRES_DATABASE,
            "host_port": POSTGRES_HOST_PORT,
            "password_encryption": "scram-sha-256",
            "wal_level": "logical",
            "max_replication_slots_min": 10,
            "max_wal_senders_min": 10,
        },
        "schemas": list(ONPREM_SCHEMAS),
        "seed_contracts": [asdict(item) for item in SEED_CONTRACTS],
        "cdc": {
            "ready": True,
            "publication": CDC_PUBLICATION,
            "future_slot": CDC_SLOT,
            "plugin": CDC_PLUGIN,
            "topic_prefix": CDC_TOPIC_PREFIX,
            "cdc_user": POSTGRES_CDC_USER,
            "published_tables": list(CDC_STAGE7D_TABLES),
            "post_stage7e_extension_tables": list(CDC_POST_STAGE7E_TABLES),
            "debezium_tested_compatible_release": DEBEZIUM_COMPATIBLE_RELEASE,
            "connector_deployed_in_stage7d": False,
        },
        "truth_boundary": {
            "product_and_retail_price": "PUBLIC_MARKET_EGYPT",
            "pharmacy_network": "SYNTHETIC_CALIBRATED",
            "purchase_cost_and_commercial_policy": "SYNTHETIC_CALIBRATED",
            "pos_transactions_in_stage7d": "SCHEMA_ONLY_NO_GENERATED_TRANSACTIONS_YET",
        },
    }


def write_database_contract(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(database_contract(), ensure_ascii=False, indent=2), encoding="utf-8")
