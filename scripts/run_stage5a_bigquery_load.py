"""Optional explicit Stage 5A BigQuery loader.

The default invocation is dry-run only. Cloud mutation requires both ``--execute`` and
``--replace`` so a local checkpoint can never create billable resources accidentally.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from pharmstock.warehouse.bigquery_contracts import (
    DEFAULT_DATASET_ID,
    DEFAULT_LOCATION,
    TABLE_CONTRACTS,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load Stage 5A local Parquet into BigQuery")
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


def _parquet_files(table_name: str) -> list[Path]:
    root = Path("artifacts/stage5a/warehouse_ready") / table_name
    return sorted(path for path in root.rglob("*.parquet") if path.is_file())


def _print_plan(project: str | None, dataset: str, location: str) -> None:
    print("=== PharmStock V2 / Stage 5A BigQuery Cloud Loader ===")
    print(f"Project:       {project or 'NOT SET'}")
    print(f"Dataset:       {dataset}")
    print(f"Location:      {location}")
    print("Default mode:  DRY RUN / NO CLOUD MUTATION")
    print("Tables:")
    for contract in TABLE_CONTRACTS.values():
        print(
            f"  {contract.table_name:<34} "
            f"files={len(_parquet_files(contract.table_name)):>3} "
            f"partition={contract.partition_field}"
        )


def _execute(project: str, dataset_id: str, location: str) -> None:
    try:
        from google.cloud import bigquery
    except ImportError as exc:
        raise RuntimeError(
            'BigQuery client is optional. Install it with: pip install -e ".[gcp]"'
        ) from exc

    client = bigquery.Client(project=project, location=location)
    dataset_ref = bigquery.Dataset(f"{project}.{dataset_id}")
    dataset_ref.location = location
    dataset_ref.description = "PharmStock Stage 5A normalized Silver warehouse"
    client.create_dataset(dataset_ref, exists_ok=True)

    for contract in TABLE_CONTRACTS.values():
        files = _parquet_files(contract.table_name)
        if not files:
            raise RuntimeError(f"no Stage 5A Parquet files for {contract.table_name}")
        table_id = f"{project}.{dataset_id}.{contract.table_name}"
        client.delete_table(table_id, not_found_ok=True)
        schema = [
            bigquery.SchemaField(
                field.name,
                field.field_type,
                mode=field.mode,
                description=field.description,
            )
            for field in contract.fields
        ]
        table = bigquery.Table(table_id, schema=schema)
        table.description = contract.description
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field=contract.partition_field,
        )
        table.clustering_fields = list(contract.clustering_fields)
        table.labels = {"platform": "pharmstock", "layer": "silver", "stage": "5a"}
        client.create_table(table)

        for path in files:
            config = bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.PARQUET,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            )
            with path.open("rb") as handle:
                job = client.load_table_from_file(
                    handle,
                    table_id,
                    job_config=config,
                    location=location,
                )
                job.result()
        loaded = client.get_table(table_id)
        print(f"  loaded {contract.table_name:<34} rows={loaded.num_rows:,}")


def main() -> None:
    args = _parser().parse_args()
    _print_plan(args.project, args.dataset, args.location)
    if not args.execute:
        print("\nSTAGE_5A_BIGQUERY_MODE=DRY_RUN")
        return
    if not args.replace:
        raise SystemExit("Cloud execution requires --replace because Stage 5A is a full refresh.")
    if not args.project or args.project == "YOUR_PROJECT_ID":
        raise SystemExit("Set --project or PHARMSTOCK_BQ_PROJECT before cloud execution.")
    _execute(args.project, args.dataset, args.location)
    print("\nSTAGE_5A_BIGQUERY_LOAD_STATUS=PASS")


if __name__ == "__main__":
    main()
