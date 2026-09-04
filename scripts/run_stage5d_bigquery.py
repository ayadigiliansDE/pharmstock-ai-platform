"""Deploy Stage 5D master-data tables to BigQuery.

Dry-run is the default. Cloud mutation requires both ``--execute`` and ``--replace``.
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pharmstock.masterdata.bigquery_cloud import (
    duplicate_primary_key_sql,
    final_table_ddl,
    load_plan_from_snapshot,
    null_violation_sql,
)
from pharmstock.masterdata.stage5d import (
    BIGQUERY_CLUSTER_FIELDS,
    BIGQUERY_SCHEMAS,
    DEFAULT_LOCATION,
    DEFAULT_MASTER_DATASET,
    MASTER_PRIMARY_KEYS,
    MASTER_TABLES,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deploy Stage 5D master data to BigQuery")
    parser.add_argument("--project", default=os.getenv("PHARMSTOCK_BQ_PROJECT"))
    parser.add_argument(
        "--dataset",
        default=os.getenv("PHARMSTOCK_BQ_MASTER_DATASET", DEFAULT_MASTER_DATASET),
    )
    parser.add_argument(
        "--location", default=os.getenv("PHARMSTOCK_BQ_LOCATION", DEFAULT_LOCATION)
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--replace", action="store_true")
    return parser


def _scalar(client, sql: str, location: str) -> int:
    row = next(iter(client.query(sql, location=location).result()))
    return int(row[0])


def _execute(args: argparse.Namespace, plan) -> dict[str, object]:
    try:
        import google.auth
        from google.api_core.exceptions import NotFound
        from google.cloud import bigquery
    except ImportError as exc:
        raise RuntimeError('Install cloud dependencies: pip install -e ".[gcp]"') from exc

    credentials, adc_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    client = bigquery.Client(
        project=args.project,
        credentials=credentials,
        location=args.location,
    )
    dataset_ref = f"{args.project}.{args.dataset}"
    try:
        dataset = client.get_dataset(dataset_ref)
        if str(dataset.location).upper() != args.location.upper():
            raise RuntimeError(
                f"Existing master dataset location {dataset.location} != {args.location}"
            )
    except NotFound:
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = args.location
        dataset.description = "PharmStock master data snapshots for analytics dimensions"
        client.create_dataset(dataset)

    staged_tables: dict[str, str] = {}
    deployed: list[dict[str, object]] = []
    try:
        # Phase 1: load and validate every table before any final table is promoted.
        for table in MASTER_TABLES:
            source = Path("artifacts/stage5d/master_ready") / f"{table}.csv"
            stage_name = f"__stage5d_{table}_{uuid.uuid4().hex[:10]}"
            stage_id = f"{args.project}.{args.dataset}.{stage_name}"
            stage = bigquery.Table(
                stage_id,
                schema=[
                    bigquery.SchemaField(name, field_type, mode=mode)
                    for name, field_type, mode in BIGQUERY_SCHEMAS[table]
                ],
            )
            stage.clustering_fields = list(BIGQUERY_CLUSTER_FIELDS[table])
            client.create_table(stage)
            staged_tables[table] = stage_id

            job_config = bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.CSV,
                skip_leading_rows=1,
                allow_quoted_newlines=True,
                encoding="UTF-8",
                schema=stage.schema,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            )
            with source.open("rb") as handle:
                client.load_table_from_file(
                    handle,
                    stage_id,
                    job_config=job_config,
                    location=args.location,
                ).result()
            staged = client.get_table(stage_id)
            expected = plan.table_counts[table]
            if int(staged.num_rows) != expected:
                raise RuntimeError(
                    f"{table}: staged row count {staged.num_rows} != expected {expected}"
                )
            nulls = _scalar(client, null_violation_sql(stage_id, table), args.location)
            if nulls:
                raise RuntimeError(f"{table}: {nulls} rows violate required-field contract")
            duplicates = _scalar(
                client, duplicate_primary_key_sql(stage_id, table), args.location
            )
            if duplicates:
                key = MASTER_PRIMARY_KEYS[table]
                raise RuntimeError(f"{table}: duplicate {key} groups={duplicates}")
            print(f"  staged   {table:<36} rows={expected:,}")

        # Phase 2: each final table replacement is atomic and starts only after all staging passed.
        for table in MASTER_TABLES:
            stage_id = staged_tables[table]
            expected = plan.table_counts[table]
            ddl = final_table_ddl(args.project, args.dataset, table, stage_id)
            client.query(ddl, location=args.location).result()
            final_id = f"{args.project}.{args.dataset}.{table}"
            final = client.get_table(final_id)
            if int(final.num_rows) != expected:
                raise RuntimeError(
                    f"{table}: final row count {final.num_rows} != expected {expected}"
                )
            final_duplicates = _scalar(
                client, duplicate_primary_key_sql(final_id, table), args.location
            )
            if final_duplicates:
                raise RuntimeError(f"{table}: final primary key is not unique")
            deployed.append(
                {
                    "table": table,
                    "table_id": final_id,
                    "row_count": expected,
                    "primary_key": MASTER_PRIMARY_KEYS[table],
                    "clustering_fields": list(BIGQUERY_CLUSTER_FIELDS[table]),
                }
            )
            print(f"  promoted {table:<36} rows={expected:,}")
    finally:
        for stage_id in staged_tables.values():
            client.delete_table(stage_id, not_found_ok=True)

    return {
        "stage": "5D",
        "executed_at": datetime.now(UTC).isoformat(),
        "cloud_mutation": True,
        "project_id": args.project,
        "adc_project": adc_project,
        "dataset_id": args.dataset,
        "location": args.location,
        "snapshot_id": plan.snapshot_id,
        "master_table_count": len(deployed),
        "total_master_rows": sum(int(item["row_count"]) for item in deployed),
        "tables": deployed,
        "monetary_measures_generated": False,
    }


def main() -> None:
    args = _parser().parse_args()
    if not args.project:
        raise SystemExit("Stage 5D requires --project or PHARMSTOCK_BQ_PROJECT")
    plan = load_plan_from_snapshot(
        snapshot_root=Path("artifacts/stage5d"),
        project_id=args.project,
        dataset_id=args.dataset,
        location=args.location,
    )
    print("=== PharmStock V2 / Stage 5D BigQuery Master Deployment ===")
    print(f"Project:          {args.project}")
    print(f"Dataset:          {args.dataset}")
    print(f"Location:         {args.location}")
    print(f"Master tables:    {len(MASTER_TABLES)}")
    print(f"Master rows:      {sum(plan.table_counts.values()):,}")

    if not args.execute:
        print("Cloud mutation:   NO / DRY RUN")
        print("\nSTAGE_5D_BIGQUERY_MODE=DRY_RUN")
        return
    if not args.replace:
        raise SystemExit("Cloud execution requires --replace to make replacement explicit")

    print("Cloud mutation:   YES")
    report = _execute(args, plan)
    output = Path("artifacts/stage5d")
    (output / "cloud_execution_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output / "_CLOUD_SUCCESS").write_text(
        "STAGE_5D_CLOUD_STATUS=PASS\n", encoding="utf-8"
    )
    print("\nSTAGE_5D_CLOUD_STATUS=PASS")


if __name__ == "__main__":
    main()
