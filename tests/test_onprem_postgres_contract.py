from __future__ import annotations

import csv
from pathlib import Path

from pharmstock.onprem import (
    CDC_PLUGIN,
    CDC_PUBLICATION,
    CDC_STAGE7D_TABLES,
    DEBEZIUM_COMPATIBLE_RELEASE,
    ONPREM_SCHEMAS,
    POSTGRES_DATABASE,
    POSTGRES_HOST_PORT,
    POSTGRES_IMAGE,
    SEED_CONTRACTS,
    database_contract,
    input_row_counts,
)
from scripts.run_checkpoint import checkpoint_command

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "infra/docker/docker-compose.postgres.yml"
SCHEMA = ROOT / "infra/docker/postgres/sql/001_schema.sql"
CDC_SQL = ROOT / "infra/docker/postgres/sql/002_roles_and_cdc.sql"
LOAD_SQL = ROOT / "infra/docker/postgres/sql/003_load_stage7d.sql"
VERIFY_SQL = ROOT / "infra/docker/postgres/sql/004_verify_stage7d.sql"


def test_stage7d_postgres_release_and_local_port_are_pinned() -> None:
    assert POSTGRES_IMAGE == "postgres:18.6"
    assert POSTGRES_DATABASE == "pharmstock_ops"
    assert POSTGRES_HOST_PORT == 5433


def test_compose_enables_logical_wal_and_scram() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    assert "image: postgres:18.6" in text
    assert "wal_level=logical" in text
    assert "max_replication_slots=10" in text
    assert "max_wal_senders=10" in text
    assert "password_encryption=scram-sha-256" in text
    assert '"${PHARMSTOCK_POSTGRES_PORT:-5433}:5432"' in text


def test_compose_uses_persistent_volume_and_project_read_only_mount() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    assert "pharmstock-postgres-data:/var/lib/postgresql/data" in text
    assert "../../:/opt/pharmstock:ro" in text


def test_schema_contains_production_operational_domains() -> None:
    text = SCHEMA.read_text(encoding="utf-8")
    for schema in ONPREM_SCHEMAS:
        assert f"CREATE SCHEMA IF NOT EXISTS {schema};" in text
    for table in (
        "master.product",
        "master.product_price_history",
        "master.pharmacy_branch",
        "commercial.product_unit_economics",
        "commercial.branch_commercial_policy",
        "pos.terminal",
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
        "procurement.goods_receipt",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in text


def test_pos_financial_constraints_are_database_enforced() -> None:
    text = SCHEMA.read_text(encoding="utf-8")
    assert "round(gross_sales_egp - discount_amount_egp, 2) = net_sales_egp" in text
    assert "round(net_sales_egp - cogs_egp, 2) = gross_profit_egp" in text
    assert "purchase_cost_egp <= retail_price_egp" in text


def test_cdc_contract_uses_pgoutput_and_precreated_publication() -> None:
    contract = database_contract()
    assert CDC_PLUGIN == "pgoutput"
    assert CDC_PUBLICATION == "pharmstock_cdc_publication"
    assert contract["cdc"]["connector_deployed_in_stage7d"] is False
    assert contract["cdc"]["published_tables"] == list(CDC_STAGE7D_TABLES)
    assert contract["cdc"]["post_stage7e_extension_tables"] == ["pos.demand_attempt"]
    assert DEBEZIUM_COMPATIBLE_RELEASE == "3.6.1.Final"


def test_cdc_sql_creates_replication_role_and_all_published_tables() -> None:
    text = CDC_SQL.read_text(encoding="utf-8")
    assert "WITH LOGIN REPLICATION" in text
    assert f"CREATE PUBLICATION {CDC_PUBLICATION}" in text
    for table in CDC_STAGE7D_TABLES:
        assert table in text


def test_master_loader_is_upsert_based_and_does_not_truncate_targets() -> None:
    text = LOAD_SQL.read_text(encoding="utf-8")
    assert "ON CONFLICT (product_id) DO UPDATE" in text
    assert "ON CONFLICT (branch_id) DO UPDATE" in text
    assert "TRUNCATE TABLE\n    staging.product" in text
    assert "TRUNCATE TABLE master.product" not in text
    assert "DELETE FROM master." not in text


def test_loader_uses_all_stage7a_7b_7c_seed_artifacts() -> None:
    text = LOAD_SQL.read_text(encoding="utf-8")
    for contract in SEED_CONTRACTS:
        assert f"/opt/pharmstock/{contract.artifact}" in text


def test_verify_sql_checks_cdc_and_referential_integrity() -> None:
    text = VERIFY_SQL.read_text(encoding="utf-8")
    for key in (
        "wal_level=",
        "publication_tables=",
        "product_finance_orphans=",
        "branch_policy_orphans=",
        "branch_org_orphans=",
        "price_product_orphans=",
        "economics_price_mismatch=",
    ):
        assert key in text


def test_input_row_counts_streams_all_seed_files(tmp_path: Path) -> None:
    expected: dict[str, int] = {}
    for index, contract in enumerate(SEED_CONTRACTS, start=1):
        path = tmp_path / contract.artifact
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow([contract.primary_key])
            for row_number in range(index):
                writer.writerow([f"id-{row_number}"])
        expected[contract.target_table] = index
    assert input_row_counts(tmp_path) == expected


def test_stage7d_truth_boundary_is_explicit() -> None:
    truth = database_contract()["truth_boundary"]
    assert truth["product_and_retail_price"] == "PUBLIC_MARKET_EGYPT"
    assert truth["pharmacy_network"] == "SYNTHETIC_CALIBRATED"
    assert truth["purchase_cost_and_commercial_policy"] == "SYNTHETIC_CALIBRATED"
    assert "NO_GENERATED_TRANSACTIONS" in truth["pos_transactions_in_stage7d"]


def test_checkpoint_launcher_knows_stage7d() -> None:
    command = checkpoint_command("7d")
    assert command[-1] == "scripts/run_stage7d_onprem.py"
