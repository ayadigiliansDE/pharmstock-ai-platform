import ast
import json
from pathlib import Path

from pharmstock.warehouse.bigquery_contracts import (
    COMMON_FIELDS,
    DEFAULT_DATASET_ID,
    DEFAULT_LOCATION,
    TABLE_CONTRACTS,
)
from pharmstock.warehouse.bigquery_plan import generate_bigquery_contract_artifacts


def test_stage5a_has_six_facts_plus_event_index() -> None:
    assert set(TABLE_CONTRACTS) == {
        "event_index",
        "sales_units_fulfilled",
        "inventory_quantity_changed",
        "inventory_reorder_required",
        "purchase_order_created",
        "goods_receipt_received",
        "restock_applied",
    }


def test_every_bigquery_table_partitions_by_materialized_event_date() -> None:
    for contract in TABLE_CONTRACTS.values():
        assert contract.partition_field == "event_date"
        assert "event_date" in contract.field_names


def test_clustering_fields_exist_and_respect_bigquery_limit() -> None:
    for contract in TABLE_CONTRACTS.values():
        assert 1 <= len(contract.clustering_fields) <= 4
        assert set(contract.clustering_fields) <= set(contract.field_names)


def test_common_lineage_contract_keeps_kafka_source_identity() -> None:
    common = {field.name: field for field in COMMON_FIELDS}

    assert common["event_id"].mode == "REQUIRED"
    assert common["kafka_topic"].field_type == "STRING"
    assert common["kafka_partition"].field_type == "INTEGER"
    assert common["kafka_offset"].field_type == "INTEGER"
    assert common["event_date"].field_type == "DATE"


def test_sales_contract_remains_non_monetary() -> None:
    fields = {field.name for field in TABLE_CONTRACTS["sales_units_fulfilled"].fields}

    assert "pricing_status" in fields
    assert "unit_price" not in fields
    assert "revenue" not in fields


def test_default_bigquery_destination_is_explicit_and_configurable() -> None:
    assert DEFAULT_DATASET_ID == "pharmstock_silver"
    assert DEFAULT_LOCATION == "EU"


def test_contract_generator_writes_schema_ddl_and_dry_run_plan(tmp_path: Path) -> None:
    catalog = generate_bigquery_contract_artifacts(tmp_path)

    assert catalog["cloud_execution"] is False
    assert catalog["table_count"] == 7
    assert (tmp_path / "bigquery_bootstrap.sql").exists()
    assert (tmp_path / "warehouse_catalog.json").exists()
    assert (tmp_path / "cloud_load_plan.json").exists()
    for table_name in TABLE_CONTRACTS:
        schema = json.loads((tmp_path / "contracts" / f"{table_name}.schema.json").read_text())
        assert schema[0]["name"] == "event_id"
        assert schema[0]["mode"] == "REQUIRED"


def test_generated_ddl_contains_partitioning_and_clustering(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("PHARMSTOCK_BQ_PROJECT", raising=False)
    monkeypatch.delenv("PHARMSTOCK_BQ_DATASET", raising=False)
    monkeypatch.delenv("PHARMSTOCK_BQ_LOCATION", raising=False)
    generate_bigquery_contract_artifacts(tmp_path)
    ddl = (tmp_path / "bigquery_bootstrap.sql").read_text(encoding="utf-8")

    assert "CREATE SCHEMA IF NOT EXISTS `YOUR_PROJECT_ID.pharmstock_silver`" in ddl
    assert "PARTITION BY `event_date`" in ddl
    assert "CLUSTER BY `branch_id`, `product_id`, `channel`" in ddl


def test_stage5a_spark_job_is_python_310_compatible() -> None:
    source = Path("spark/jobs/stage5a_warehouse_export.py").read_text(encoding="utf-8")

    ast.parse(source, filename="stage5a_warehouse_export.py", feature_version=(3, 10))
    assert "from datetime import UTC" not in source
    assert "datetime.now(timezone.utc)" in source


def test_stage5a_spark_job_uses_dependency_light_contract_module() -> None:
    source = Path("spark/jobs/stage5a_warehouse_export.py").read_text(encoding="utf-8")

    assert "from pharmstock.warehouse.bigquery_contracts import" in source
    assert "google.cloud" not in source
    assert "pydantic" not in source


def test_cloud_loader_requires_explicit_execute_and_replace() -> None:
    source = Path("scripts/run_stage5a_bigquery_load.py").read_text(encoding="utf-8")

    assert 'parser.add_argument("--execute", action="store_true")' in source
    assert 'parser.add_argument("--replace", action="store_true")' in source
    assert "STAGE_5A_BIGQUERY_MODE=DRY_RUN" in source


def test_bigquery_client_is_optional_not_core_dependency() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'google-cloud-bigquery==3.43.0' in pyproject
    core_dependencies = pyproject.split("[project.optional-dependencies]", 1)[0]
    assert "google-cloud-bigquery" not in core_dependencies


def test_stage5a_checkpoint_is_registered() -> None:
    source = Path("scripts/run_checkpoint.py").read_text(encoding="utf-8")

    assert 'if checkpoint == "5a":' in source
    assert '"scripts/run_stage5a_checkpoint.py"' in source
