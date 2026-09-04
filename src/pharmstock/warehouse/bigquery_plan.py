"""Generate deterministic BigQuery DDL, schemas, and local load plans for Stage 5A."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pharmstock.warehouse.bigquery_contracts import (
    DEFAULT_DATASET_ID,
    DEFAULT_LOCATION,
    TABLE_CONTRACTS,
    BigQueryTableContract,
)


def _project_id() -> str:
    return os.getenv("PHARMSTOCK_BQ_PROJECT", "YOUR_PROJECT_ID").strip() or "YOUR_PROJECT_ID"


def _dataset_id() -> str:
    return os.getenv("PHARMSTOCK_BQ_DATASET", DEFAULT_DATASET_ID).strip() or DEFAULT_DATASET_ID


def _location() -> str:
    return os.getenv("PHARMSTOCK_BQ_LOCATION", DEFAULT_LOCATION).strip() or DEFAULT_LOCATION


def _ddl_type(field_type: str) -> str:
    mapping = {
        "STRING": "STRING",
        "TIMESTAMP": "TIMESTAMP",
        "DATE": "DATE",
        "INTEGER": "INT64",
        "BOOLEAN": "BOOL",
    }
    return mapping[field_type]


def _table_ddl(project_id: str, dataset_id: str, contract: BigQueryTableContract) -> str:
    columns = ",\n".join(
        f"  `{field.name}` {_ddl_type(field.field_type)}"
        for field in contract.fields
    )
    cluster = ""
    if contract.clustering_fields:
        cluster = "\nCLUSTER BY " + ", ".join(f"`{name}`" for name in contract.clustering_fields)
    return (
        f"CREATE TABLE IF NOT EXISTS `{project_id}.{dataset_id}.{contract.table_name}` (\n"
        f"{columns}\n)\n"
        f"PARTITION BY `{contract.partition_field}`"
        f"{cluster}\n"
        f"OPTIONS(description={json.dumps(contract.description)});"
    )


def generate_bigquery_contract_artifacts(output_root: Path) -> dict[str, object]:
    """Write all cloud-independent BigQuery contract artifacts and return the catalog."""

    project_id = _project_id()
    dataset_id = _dataset_id()
    location = _location()
    contracts_dir = output_root / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)

    catalog_tables: list[dict[str, object]] = []
    ddl_sections = [
        "-- PharmStock Stage 5A BigQuery bootstrap",
        "-- Replace YOUR_PROJECT_ID or set PHARMSTOCK_BQ_PROJECT before cloud execution.",
        (
            f"CREATE SCHEMA IF NOT EXISTS `{project_id}.{dataset_id}`\n"
            f"OPTIONS(location={json.dumps(location)});"
        ),
    ]

    for table_name, contract in TABLE_CONTRACTS.items():
        schema_path = contracts_dir / f"{table_name}.schema.json"
        schema_path.write_text(
            json.dumps([field.to_api_repr() for field in contract.fields], indent=2),
            encoding="utf-8",
        )
        ddl_sections.append(_table_ddl(project_id, dataset_id, contract))
        catalog_tables.append(
            {
                **contract.to_catalog_entry(),
                "local_parquet_glob": (
                    f"artifacts/stage5a/warehouse_ready/{table_name}/**/*.parquet"
                ),
                "schema_file": f"contracts/{table_name}.schema.json",
                "write_strategy": "replace_table_then_append_local_parquet_parts",
            }
        )

    bootstrap_sql = output_root / "bigquery_bootstrap.sql"
    bootstrap_sql.write_text("\n\n".join(ddl_sections) + "\n", encoding="utf-8")

    catalog: dict[str, object] = {
        "stage": "5A",
        "warehouse": "BigQuery",
        "project_id": project_id,
        "dataset_id": dataset_id,
        "location": location,
        "cloud_execution": False,
        "source_layer": "Stage 4B Silver Parquet",
        "local_export": "BigQuery-ready Parquet with event_date materialized in-file",
        "table_count": len(catalog_tables),
        "tables": catalog_tables,
    }
    (output_root / "warehouse_catalog.json").write_text(
        json.dumps(catalog, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output_root / "cloud_load_plan.json").write_text(
        json.dumps(
            {
                "mode": "dry_run_contract_only",
                "requires": [
                    "Google Cloud project with BigQuery API enabled",
                    "Application Default Credentials or equivalent explicit credentials",
                    "optional dependency: pip install -e .[gcp]",
                ],
                "project_id": project_id,
                "dataset_id": dataset_id,
                "location": location,
                "tables": [
                    {
                        "table": table["table_name"],
                        "source": table["local_parquet_glob"],
                        "partition_field": table["partition_field"],
                        "clustering_fields": table["clustering_fields"],
                    }
                    for table in catalog_tables
                ],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return catalog


__all__ = ["generate_bigquery_contract_artifacts"]
