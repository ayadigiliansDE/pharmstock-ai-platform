"""Fresh BigQuery Sandbox raw rebuild directly from Stage 7G Parquet.

This recovery path intentionally bypasses Stage 7H staging/promotion tables.
It is designed for BigQuery Sandbox, where:
- storage is capped at 10 GiB active storage;
- tables and partitions expire after 60 days;
- historical date partitions older than 60 days can disappear immediately.

The script therefore loads each Stage 7G Parquet table directly into its final
UNPARTITIONED BigQuery raw table, preserving production partition definitions
in project metadata while avoiding temporary duplicate copies.

Usage:
  First clean restart (destructive only to Stage 7H cloud datasets):
    python scripts/run_stage7h_sandbox_fresh.py --execute --reset

  Resume after interruption:
    python scripts/run_stage7h_sandbox_fresh.py --execute
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pharmstock.rebuild.bigquery_stage import (
    TABLE_LAYOUTS,
    config_from_environment,
    duplicate_primary_key_sql,
    load_stage7g_plan,
    parquet_files,
)

SANDBOX_TTL_MS = 60 * 24 * 60 * 60 * 1000
SOFT_STORAGE_LIMIT_GIB = 9.25


def _parser() -> argparse.ArgumentParser:
    defaults = config_from_environment()
    parser = argparse.ArgumentParser(
        description="Fresh/resumable Stage 7H Sandbox direct raw reload"
    )
    parser.add_argument("--project", default=defaults.project_id)
    parser.add_argument("--dataset", default=defaults.dataset_id)
    parser.add_argument("--location", default=defaults.location)
    parser.add_argument("--dbt-base-dataset", default=defaults.dbt_base_dataset)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--reset",
        action="store_true",
        help=(
            "Delete only Stage 7H raw/rebuild dbt datasets before direct reload. "
            "Use once for a clean restart."
        ),
    )
    return parser


def _scalar(client: object, sql: str, location: str) -> int:
    rows = list(client.query(sql, location=location).result())
    if len(rows) != 1:
        raise RuntimeError("expected one scalar BigQuery result")
    return int(rows[0][0])


def _real_count(client: object, table_id: str, location: str) -> int:
    return _scalar(client, f"SELECT COUNT(*) FROM `{table_id}`", location)


def _is_not_found(exc: Exception) -> bool:
    return exc.__class__.__name__ == "NotFound" or getattr(exc, "code", None) == 404


def _existing_valid_final(
    *,
    client: object,
    table_id: str,
    expected_rows: int,
    primary_key: tuple[str, ...],
    location: str,
) -> bool:
    try:
        table = client.get_table(table_id)
    except Exception as exc:
        if _is_not_found(exc):
            return False
        raise
    if table.time_partitioning is not None:
        return False
    if _real_count(client, table_id, location) != expected_rows:
        return False
    duplicates = _scalar(
        client,
        duplicate_primary_key_sql(table_id, primary_key),
        location,
    )
    return duplicates == 0


def _human_mib(size_bytes: int) -> str:
    return f"{size_bytes / (1024 * 1024):,.1f} MiB"


def _dataset_storage_gib(client: object, dataset_id: str) -> float:
    total = 0
    for item in client.list_tables(dataset_id):
        try:
            total += int(client.get_table(item.reference).num_bytes or 0)
        except Exception:
            continue
    return total / (1024**3)


def _create_raw_dataset(
    *,
    client: object,
    bigquery: object,
    dataset_id: str,
    location: str,
) -> None:
    dataset = bigquery.Dataset(dataset_id)
    dataset.location = location
    dataset.description = "PharmStock Stage 7H Sandbox raw rebuild"
    dataset.labels = {
        "platform": "pharmstock",
        "stage": "7h",
        "layer": "rebuild_raw",
        "mode": "sandbox",
    }
    client.create_dataset(dataset, exists_ok=True, timeout=30)
    actual = client.get_dataset(dataset_id)
    if actual.location.upper() != location.upper():
        raise RuntimeError(
            f"dataset location mismatch expected={location} actual={actual.location}"
        )
    print(
        "Dataset TTLs: "
        f"table={actual.default_table_expiration_ms} "
        f"partition={actual.default_partition_expiration_ms}",
        flush=True,
    )
    if actual.default_table_expiration_ms not in {None, SANDBOX_TTL_MS}:
        print("WARNING: unexpected table TTL for Sandbox dataset", flush=True)


def _reset_stage7h_cloud(
    *,
    client: object,
    project_id: str,
    raw_dataset: str,
    dbt_staging_dataset: str,
    dbt_gold_dataset: str,
) -> None:
    targets = (raw_dataset, dbt_staging_dataset, dbt_gold_dataset)
    print("\nRESET Stage 7H cloud datasets:", flush=True)
    for dataset in targets:
        dataset_id = f"{project_id}.{dataset}"
        print(f"  delete {dataset_id}", flush=True)
        client.delete_dataset(
            dataset_id,
            delete_contents=True,
            not_found_ok=True,
        )


def _load_direct_final(
    *,
    client: object,
    bigquery: object,
    target_id: str,
    source_table: str,
    files: tuple[Path, ...],
    expected_rows: int,
    primary_key: tuple[str, ...],
    location: str,
) -> None:
    if expected_rows and not files:
        raise RuntimeError(f"{source_table}: no Parquet files found")

    # If a previous attempt left a partial/mis-shaped final, restart only this table.
    client.delete_table(target_id, not_found_ok=True)
    layout = TABLE_LAYOUTS[source_table]
    total_files = len(files)

    for index, path in enumerate(files, start=1):
        config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.PARQUET,
            autodetect=True,
            write_disposition=(
                bigquery.WriteDisposition.WRITE_TRUNCATE
                if index == 1
                else bigquery.WriteDisposition.WRITE_APPEND
            ),
        )
        # Create the final table clustered but deliberately UNPARTITIONED in Sandbox.
        if index == 1 and layout.clustering_fields:
            config.clustering_fields = list(layout.clustering_fields)

        with path.open("rb") as handle:
            job = client.load_table_from_file(
                handle,
                target_id,
                job_config=config,
                location=location,
            )
            print(
                f"    upload {source_table:<38} "
                f"file={index:>2}/{total_files:<2} "
                f"size={_human_mib(path.stat().st_size):>11} job={job.job_id}",
                flush=True,
            )
            job.result()

    actual_rows = 0 if expected_rows == 0 else _real_count(client, target_id, location)
    if actual_rows != expected_rows:
        raise RuntimeError(
            f"{source_table}: direct final rows {actual_rows} != {expected_rows}; "
            "table preserved for diagnosis"
        )

    duplicates = _scalar(
        client,
        duplicate_primary_key_sql(target_id, primary_key),
        location,
    )
    if duplicates:
        raise RuntimeError(
            f"{source_table}: duplicate primary keys detected; table preserved"
        )

    table = client.get_table(target_id)
    if table.time_partitioning is not None:
        raise RuntimeError(
            f"{source_table}: Sandbox direct final unexpectedly partitioned"
        )
    table.description = (
        f"PharmStock Stage 7H Sandbox raw rebuild of {source_table}; "
        f"production partition={layout.partition_expression or 'NONE'}"
    )
    table.labels = {
        "platform": "pharmstock",
        "stage": "7h",
        "layer": "rebuild_raw",
        "mode": "sandbox",
    }
    client.update_table(table, ["description", "labels"])


def main() -> None:
    args = _parser().parse_args()
    if not args.execute:
        raise SystemExit(
            "Refusing cloud mutation without --execute. "
            "Use --execute --reset once, then --execute to resume."
        )
    if not args.project:
        raise SystemExit("PHARMSTOCK_BQ_PROJECT / --project is required")

    try:
        import google.auth
        from google.cloud import bigquery
    except ImportError as exc:
        raise RuntimeError(
            'Install cloud dependencies with: pip install -e ".[gcp,analytics]"'
        ) from exc

    credentials, _ = google.auth.default()
    client = bigquery.Client(
        project=args.project,
        credentials=credentials,
        location=args.location,
    )

    dbt_staging = f"{args.dbt_base_dataset}_rebuild_stg"
    dbt_gold = f"{args.dbt_base_dataset}_rebuild_gold"

    print("=== Stage 7H Sandbox Fresh Direct Reload ===")
    print(f"Project:          {args.project}")
    print(f"Raw dataset:      {args.dataset}")
    print(f"Location:         {args.location}")
    print("Physical layout:  UNPARTITIONED + CLUSTERED")
    print("Temporary stage:  NONE")
    print("Historical Kafka: NO")
    print(f"Reset requested:  {'YES' if args.reset else 'NO / RESUME'}")

    if args.reset:
        _reset_stage7h_cloud(
            client=client,
            project_id=args.project,
            raw_dataset=args.dataset,
            dbt_staging_dataset=dbt_staging,
            dbt_gold_dataset=dbt_gold,
        )

    dataset_id = f"{args.project}.{args.dataset}"
    _create_raw_dataset(
        client=client,
        bigquery=bigquery,
        dataset_id=dataset_id,
        location=args.location,
    )

    plan = load_stage7g_plan()
    tables = plan["snapshot_tables"]
    completed = 0
    total_rows = 0

    print("\nDirect raw reload:")
    for index, raw_item in enumerate(tables, start=1):
        assert isinstance(raw_item, dict)
        source_table = str(raw_item["source_table"])
        target_name = str(raw_item["target_table"]).split(".", 1)[1]
        target_id = f"{args.project}.{args.dataset}.{target_name}"
        expected_rows = int(raw_item["rows"])
        primary_key = tuple(str(value) for value in raw_item["primary_key"])
        files = parquet_files(Path(str(raw_item["local_parquet_path"])))

        if _existing_valid_final(
            client=client,
            table_id=target_id,
            expected_rows=expected_rows,
            primary_key=primary_key,
            location=args.location,
        ):
            print(
                f"  resume [{index:>2}/{len(tables)}] {source_table:<44} "
                f"rows={expected_rows:>10,} (valid final)",
                flush=True,
            )
        else:
            current_gib = _dataset_storage_gib(client, dataset_id)
            if current_gib >= SOFT_STORAGE_LIMIT_GIB:
                raise RuntimeError(
                    f"Sandbox storage safety stop: {current_gib:.3f} GiB >= "
                    f"{SOFT_STORAGE_LIMIT_GIB:.2f} GiB before {source_table}. "
                    "No completed finals were deleted."
                )
            print(
                f"  load   [{index:>2}/{len(tables)}] {source_table:<44} "
                f"files={len(files):>2} rows={expected_rows:>10,}",
                flush=True,
            )
            _load_direct_final(
                client=client,
                bigquery=bigquery,
                target_id=target_id,
                source_table=source_table,
                files=files,
                expected_rows=expected_rows,
                primary_key=primary_key,
                location=args.location,
            )
            storage_gib = _dataset_storage_gib(client, dataset_id)
            print(
                f"  PASS   [{index:>2}/{len(tables)}] {source_table:<44} "
                f"rows={expected_rows:>10,} raw_storage≈{storage_gib:.3f} GiB",
                flush=True,
            )

        completed += 1
        total_rows += expected_rows

    print("\nStage 7H Sandbox raw verification:")
    print(f"Raw finals:        {completed}/26")
    print(f"Raw rows:          {total_rows:,}")
    print("Layout:            UNPARTITIONED + CLUSTERED")
    print("Temporary copies:  NONE")
    print("Cloud mutation:    YES")
    print("STAGE_7H_SANDBOX_RAW_STATUS=PASS")
    print("NEXT: run scripts\\run_stage7h_cloud.py --execute --replace")
    print("      It should resume 26/26 and continue to dbt only.")


if __name__ == "__main__":
    main()
