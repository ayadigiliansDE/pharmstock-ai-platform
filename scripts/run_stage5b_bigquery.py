"""Explicit Stage 5B live BigQuery deployment.

Default invocation is dry-run only. Actual cloud mutation requires both ``--execute`` and
``--replace`` plus a real project ID and Application Default Credentials (ADC).
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pharmstock.warehouse.bigquery_cloud import (
    BigQueryCloudConfig,
    assess_bigquery_readiness,
    discover_local_warehouse,
)
from pharmstock.warehouse.bigquery_contracts import (
    DEFAULT_DATASET_ID,
    DEFAULT_LOCATION,
    TABLE_CONTRACTS,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deploy Stage 5A warehouse to BigQuery")
    parser.add_argument("--project", default=os.getenv("PHARMSTOCK_BQ_PROJECT"))
    parser.add_argument(
        "--dataset", default=os.getenv("PHARMSTOCK_BQ_DATASET", DEFAULT_DATASET_ID)
    )
    parser.add_argument(
        "--location", default=os.getenv("PHARMSTOCK_BQ_LOCATION", DEFAULT_LOCATION)
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--replace", action="store_true")
    return parser


def _schema_fields(
    bigquery: object, contract: object, *, relax_required: bool = False
) -> list[object]:
    return [
        bigquery.SchemaField(
            field.name,
            field.field_type,
            mode=("NULLABLE" if relax_required and field.mode == "REQUIRED" else field.mode),
            description=field.description,
        )
        for field in contract.fields
    ]


def _new_table(bigquery: object, table_id: str, contract: object, *, staging: bool) -> object:
    table = bigquery.Table(
        table_id,
        schema=_schema_fields(bigquery, contract, relax_required=staging),
    )
    table.description = (
        f"Temporary Stage 5B load table for {contract.table_name}"
        if staging
        else contract.description
    )
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field=contract.partition_field,
    )
    table.clustering_fields = list(contract.clustering_fields)
    table.labels = {
        "platform": "pharmstock",
        "layer": "silver",
        "stage": "5b",
        "temporary": "true" if staging else "false",
    }
    return table


def _field_signature(table: object) -> tuple[tuple[str, str, str], ...]:
    return tuple((field.name, field.field_type, field.mode) for field in table.schema)


def _contract_signature(contract: object) -> tuple[tuple[str, str, str], ...]:
    return tuple((field.name, field.field_type, field.mode) for field in contract.fields)


def _validate_target_metadata(table: object, contract: object) -> None:
    if _field_signature(table) != _contract_signature(contract):
        raise RuntimeError(f"BigQuery target schema drift: {table.full_table_id}")
    partition_field = getattr(getattr(table, "time_partitioning", None), "field", None)
    if partition_field != contract.partition_field:
        raise RuntimeError(f"BigQuery target partition drift: {table.full_table_id}")
    if tuple(table.clustering_fields or ()) != tuple(contract.clustering_fields):
        raise RuntimeError(f"BigQuery target clustering drift: {table.full_table_id}")


def _ensure_dataset(client: object, bigquery: object, config: BigQueryCloudConfig) -> None:
    dataset = bigquery.Dataset(f"{config.project_id}.{config.dataset_id}")
    dataset.location = config.location
    dataset.description = "PharmStock normalized Silver warehouse"
    dataset.labels = {"platform": "pharmstock", "stage": "5b"}
    client.create_dataset(dataset, exists_ok=True, timeout=30)
    actual = client.get_dataset(f"{config.project_id}.{config.dataset_id}")
    if actual.location.upper() != config.location.upper():
        raise RuntimeError(
            "BigQuery dataset location mismatch: "
            f"expected={config.location} actual={actual.location}"
        )


def _ensure_target(client: object, bigquery: object, table_id: str, contract: object) -> None:
    from google.api_core.exceptions import NotFound

    try:
        table = client.get_table(table_id)
    except NotFound:
        table = client.create_table(_new_table(bigquery, table_id, contract, staging=False))
    _validate_target_metadata(table, contract)


def _load_staging(
    client: object,
    bigquery: object,
    *,
    table_id: str,
    contract: object,
    files: tuple[Path, ...],
    location: str,
) -> int:
    client.create_table(_new_table(bigquery, table_id, contract, staging=True))
    for path in files:
        config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.PARQUET,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        )
        with path.open("rb") as handle:
            client.load_table_from_file(
                handle,
                table_id,
                job_config=config,
                location=location,
            ).result()
    return int(client.get_table(table_id).num_rows)


_DDL_TYPES = {
    "STRING": "STRING",
    "TIMESTAMP": "TIMESTAMP",
    "DATE": "DATE",
    "INTEGER": "INT64",
    "BOOLEAN": "BOOL",
}


def _required_field_names(contract: object) -> tuple[str, ...]:
    return tuple(field.name for field in contract.fields if field.mode == "REQUIRED")


def _validate_required_values(
    client: object, *, table_id: str, contract: object, location: str
) -> None:
    required = _required_field_names(contract)
    if not required:
        return
    predicate = " OR ".join(f"`{name}` IS NULL" for name in required)
    sql = f"SELECT COUNT(*) AS invalid_rows FROM `{table_id}` WHERE {predicate}"
    rows = client.query(sql, location=location).result()
    first = next(iter(rows), None)
    invalid_rows = int(first.invalid_rows) if first is not None else 0
    if invalid_rows:
        raise RuntimeError(
            f"staging contains NULL in REQUIRED fields for {contract.table_name}: "
            f"rows={invalid_rows}"
        )


def _promotion_sql(*, staging_id: str, target_id: str, contract: object) -> str:
    columns = []
    selects = []
    for field in contract.fields:
        sql_type = _DDL_TYPES[field.field_type]
        not_null = " NOT NULL" if field.mode == "REQUIRED" else ""
        columns.append(f"  `{field.name}` {sql_type}{not_null}")
        selects.append(f"`{field.name}`")
    cluster = ", ".join(f"`{name}`" for name in contract.clustering_fields)
    return (
        f"CREATE OR REPLACE TABLE `{target_id}` (\n"
        + ",\n".join(columns)
        + f"\n)\nPARTITION BY `{contract.partition_field}`\n"
        + f"CLUSTER BY {cluster}\nAS\nSELECT {', '.join(selects)}\n"
        + f"FROM `{staging_id}`"
    )


def _promote(
    client: object,
    *,
    staging_id: str,
    target_id: str,
    contract: object,
    location: str,
) -> None:
    sql = _promotion_sql(staging_id=staging_id, target_id=target_id, contract=contract)
    client.query(sql, location=location).result()


def _execute(config: BigQueryCloudConfig) -> dict[str, object]:
    try:
        import google.auth
        from google.cloud import bigquery
    except ImportError as exc:
        raise RuntimeError(
            'BigQuery client is optional. Install it with: pip install -e ".[gcp]"'
        ) from exc

    credentials, adc_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    client = bigquery.Client(
        project=config.project_id,
        credentials=credentials,
        location=config.location,
    )
    _ensure_dataset(client, bigquery, config)
    local_tables = discover_local_warehouse(Path("artifacts/stage5a"))
    run_id = uuid4().hex[:10]
    report_tables: list[dict[str, object]] = []

    for local in local_tables:
        contract = TABLE_CONTRACTS[local.table_name]
        target_id = f"{config.project_id}.{config.dataset_id}.{local.table_name}"
        staging_name = f"__stage5b_{local.table_name}_{run_id}"
        staging_id = f"{config.project_id}.{config.dataset_id}.{staging_name}"
        _ensure_target(client, bigquery, target_id, contract)
        try:
            staged_rows = _load_staging(
                client,
                bigquery,
                table_id=staging_id,
                contract=contract,
                files=local.parquet_files,
                location=config.location,
            )
            if staged_rows != local.expected_rows:
                raise RuntimeError(
                    f"staging row mismatch {local.table_name}: "
                    f"expected={local.expected_rows} actual={staged_rows}"
                )
            _validate_required_values(
                client,
                table_id=staging_id,
                contract=contract,
                location=config.location,
            )
            _promote(
                client,
                staging_id=staging_id,
                target_id=target_id,
                contract=contract,
                location=config.location,
            )
            target = client.get_table(target_id)
            target.schema = _schema_fields(bigquery, contract)
            target.description = contract.description
            target.labels = {
                "platform": "pharmstock",
                "layer": "silver",
                "stage": "5b",
                "temporary": "false",
            }
            target = client.update_table(target, ["schema", "description", "labels"])
            _validate_target_metadata(target, contract)
            if int(target.num_rows) != local.expected_rows:
                raise RuntimeError(
                    f"target row mismatch {local.table_name}: "
                    f"expected={local.expected_rows} actual={target.num_rows}"
                )
            report_tables.append(
                {
                    "table_name": local.table_name,
                    "expected_rows": local.expected_rows,
                    "staged_rows": staged_rows,
                    "target_rows": int(target.num_rows),
                    "required_null_rows": 0,
                    "target_id": target_id,
                }
            )
            print(f"  promoted {local.table_name:<34} rows={int(target.num_rows):,}")
        finally:
            client.delete_table(staging_id, not_found_ok=True)

    return {
        "stage": "5B",
        "executed_at": datetime.now(UTC).isoformat(),
        "cloud_mutation": True,
        "project_id": config.project_id,
        "adc_project": adc_project,
        "dataset_id": config.dataset_id,
        "location": config.location,
        "table_count": len(report_tables),
        "tables": report_tables,
    }


def main() -> None:
    args = _parser().parse_args()
    config = BigQueryCloudConfig(args.project, args.dataset, args.location)
    readiness = assess_bigquery_readiness(Path("artifacts/stage5a"), config)

    print("=== PharmStock V2 / Stage 5B BigQuery Live Deployment ===")
    print(f"Project:          {config.project_id or 'NOT SET'}")
    print(f"Dataset:          {config.dataset_id}")
    print(f"Location:         {config.location}")
    print(f"Local ready:      {'YES' if readiness.local_ready else 'NO'}")
    print(f"Client installed: {'YES' if readiness.client_installed else 'NO'}")
    print(f"Project set:      {'YES' if readiness.project_configured else 'NO'}")
    print(f"ADC hint:         {'YES' if readiness.credential_hint_present else 'NO'}")

    if not args.execute:
        print("Cloud mutation:   NO / DRY RUN")
        print("\nSTAGE_5B_BIGQUERY_MODE=DRY_RUN")
        return
    if not args.replace:
        raise SystemExit("Cloud execution requires --replace for Stage 5B full refresh.")
    if not readiness.local_ready:
        raise SystemExit("Stage 5A local warehouse is not ready.")
    if not readiness.client_installed:
        raise SystemExit('Install the optional client first: pip install -e ".[gcp]"')
    if not readiness.project_configured:
        raise SystemExit("Set --project or PHARMSTOCK_BQ_PROJECT before cloud execution.")
    if not readiness.dataset_id_valid:
        raise SystemExit("BigQuery dataset id is invalid.")

    report = _execute(config)
    output = Path("artifacts/stage5b")
    output.mkdir(parents=True, exist_ok=True)
    (output / "cloud_execution_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    print("\nSTAGE_5B_CLOUD_STATUS=PASS")


if __name__ == "__main__":
    main()
