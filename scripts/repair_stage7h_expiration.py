"""Repair Stage 7H for BigQuery Sandbox without re-uploading valid cloud data.

BigQuery Sandbox forces a 60-day lifetime on tables and partitions. Time-based
partitioned raw tables therefore cannot safely hold a one-year historical
snapshot: partitions older than 60 days can expire as soon as the table is
created. This repair keeps the sandbox table TTL, but repacks Stage 7H raw
finals as unpartitioned, clustered tables so the complete history survives for
the table's sandbox lifetime.
"""

from __future__ import annotations

import argparse
import os
from collections import defaultdict
from datetime import UTC

from google.cloud import bigquery

from pharmstock.rebuild.bigquery_stage import (
    TABLE_LAYOUTS,
    atomic_replace_sql,
    duplicate_primary_key_sql,
    load_stage7g_plan,
)

DEFAULT_PROJECT = "pharmstock-ai-platform-2026"
DEFAULT_DATASET = "pharmstock_ops_rebuild"
DEFAULT_LOCATION = "EU"
SANDBOX_TTL_MS = 60 * 24 * 60 * 60 * 1000


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Repair Stage 7H raw finals for BigQuery Sandbox"
    )
    parser.add_argument(
        "--project",
        default=os.getenv("PHARMSTOCK_BQ_PROJECT", DEFAULT_PROJECT),
    )
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--location", default=DEFAULT_LOCATION)
    parser.add_argument("--job-limit", type=int, default=3000)
    return parser


def _scalar(client: bigquery.Client, sql: str, location: str) -> int:
    rows = list(client.query(sql, location=location).result())
    if len(rows) != 1:
        raise RuntimeError("expected one scalar BigQuery result")
    return int(rows[0][0])


def _count(client: bigquery.Client, table_id: str, location: str) -> int:
    return _scalar(client, f"SELECT COUNT(*) FROM `{table_id}`", location)


def _not_found(exc: Exception) -> bool:
    return exc.__class__.__name__ == "NotFound" or getattr(exc, "code", None) == 404


def _sandbox_dataset(dataset: bigquery.Dataset) -> bool:
    return (
        dataset.default_table_expiration_ms == SANDBOX_TTL_MS
        and dataset.default_partition_expiration_ms == SANDBOX_TTL_MS
    )


def _full_current_recovery(
    client: bigquery.Client,
    project: str,
    dataset: str,
    target_name: str,
    expected_rows: int,
    location: str,
) -> str | None:
    prefixes = (
        f"__recovered_stage7h_{target_name}",
        f"__stage7h_{target_name}_",
        f"__sandbox_repack_stage7h_{target_name}",
    )
    dataset_ref = f"{project}.{dataset}"
    for table_item in client.list_tables(dataset_ref):
        if not table_item.table_id.startswith(prefixes):
            continue
        table_id = f"{project}.{dataset}.{table_item.table_id}"
        try:
            actual = _count(client, table_id, location)
        except Exception:
            continue
        if actual == expected_rows:
            print(f"    reuse cloud stage: {table_item.table_id} ({actual:,})")
            return table_id
    return None


def _recent_stage_jobs(
    client: bigquery.Client,
    dataset: str,
    target_name: str,
    job_limit: int,
) -> list[bigquery.LoadJob]:
    by_stage: dict[str, list[bigquery.LoadJob]] = defaultdict(list)
    prefix = f"__stage7h_{target_name}_"
    for job in client.list_jobs(max_results=job_limit):
        if getattr(job, "job_type", None) != "load":
            continue
        destination = getattr(job, "destination", None)
        if destination is None:
            continue
        if destination.dataset_id != dataset:
            continue
        if not destination.table_id.startswith(prefix):
            continue
        if getattr(job, "state", None) != "DONE":
            continue
        if getattr(job, "error_result", None):
            continue
        by_stage[destination.table_id].append(job)

    last_jobs: list[bigquery.LoadJob] = []
    for jobs in by_stage.values():
        complete = [job for job in jobs if getattr(job, "ended", None) is not None]
        if complete:
            last_jobs.append(max(complete, key=lambda item: item.ended))
    return sorted(last_jobs, key=lambda item: item.ended, reverse=True)


def _restore_deleted_full_stage(
    client: bigquery.Client,
    project: str,
    dataset: str,
    target_name: str,
    expected_rows: int,
    location: str,
    job_limit: int,
) -> str | None:
    jobs = _recent_stage_jobs(client, dataset, target_name, job_limit)
    if not jobs:
        return None

    recovered_id = f"{project}.{dataset}.__recovered_stage7h_{target_name}"
    for job in jobs:
        destination = job.destination
        assert destination is not None
        ended = job.ended
        assert ended is not None
        snapshot_ms = int(ended.astimezone(UTC).timestamp() * 1000)
        stage_id = f"{project}.{dataset}.{destination.table_id}"
        snapshot_id = f"{stage_id}@{snapshot_ms}"
        print(
            f"    restore candidate: {destination.table_id} "
            f"snapshot={snapshot_ms} job={job.job_id}"
        )
        client.delete_table(recovered_id, not_found_ok=True)
        try:
            copy_job = client.copy_table(snapshot_id, recovered_id, location=location)
            copy_job.result()
            actual = _count(client, recovered_id, location)
        except Exception as exc:
            print(f"      restore failed: {exc.__class__.__name__}: {exc}")
            client.delete_table(recovered_id, not_found_ok=True)
            continue
        print(f"      recovered rows: {actual:,}")
        if actual == expected_rows:
            return recovered_id
        client.delete_table(recovered_id, not_found_ok=True)
    return None


def _snapshot_full_partitioned_final(
    client: bigquery.Client,
    *,
    project: str,
    dataset: str,
    target_name: str,
    target_id: str,
    expected_rows: int,
    location: str,
) -> str | None:
    recovered_id = f"{project}.{dataset}.__sandbox_repack_stage7h_{target_name}"
    client.delete_table(recovered_id, not_found_ok=True)
    try:
        client.query(
            f"CREATE TABLE `{recovered_id}` AS SELECT * FROM `{target_id}`",
            location=location,
        ).result()
        actual = _count(client, recovered_id, location)
    except Exception as exc:
        print(f"    repack snapshot failed: {exc.__class__.__name__}: {exc}")
        client.delete_table(recovered_id, not_found_ok=True)
        return None
    if actual != expected_rows:
        print(f"    repack snapshot incomplete: {actual:,} != {expected_rows:,}")
        client.delete_table(recovered_id, not_found_ok=True)
        return None
    print(f"    snapshotted full partitioned final: {actual:,} rows")
    return recovered_id


def _promote_unpartitioned(
    client: bigquery.Client,
    *,
    recovered_id: str,
    target_id: str,
    source_table: str,
    primary_key: tuple[str, ...],
    expected_rows: int,
    location: str,
) -> None:
    recovered_rows = _count(client, recovered_id, location)
    if recovered_rows != expected_rows:
        raise RuntimeError(
            f"recovered row count mismatch: {recovered_rows:,} != {expected_rows:,}"
        )
    duplicates = _scalar(
        client,
        duplicate_primary_key_sql(recovered_id, primary_key),
        location,
    )
    if duplicates:
        raise RuntimeError(f"recovered staging has {duplicates:,} duplicate PK groups")

    client.delete_table(target_id, not_found_ok=True)
    client.query(
        atomic_replace_sql(
            target_table_id=target_id,
            staging_table_id=recovered_id,
            source_table=source_table,
            partitioning_enabled=False,
        ),
        location=location,
    ).result()

    final_rows = _count(client, target_id, location)
    if final_rows != expected_rows:
        raise RuntimeError(
            "sandbox promotion mismatch; recovery preserved: "
            f"{final_rows:,} != {expected_rows:,} at {recovered_id}"
        )
    final = client.get_table(target_id)
    if final.time_partitioning is not None:
        raise RuntimeError(
            f"sandbox final unexpectedly partitioned; recovery preserved: {recovered_id}"
        )
    client.delete_table(recovered_id, not_found_ok=True)


def main() -> None:
    args = _parser().parse_args()
    client = bigquery.Client(project=args.project, location=args.location)
    dataset_id = f"{args.project}.{args.dataset}"
    dataset = client.get_dataset(dataset_id)

    print("=== Stage 7H BigQuery Sandbox recovery ===")
    print(f"Project:   {args.project}")
    print(f"Dataset:   {args.dataset}")
    print(f"Location:  {args.location}")
    print(f"Table TTL: {dataset.default_table_expiration_ms}")
    print(f"Part TTL:  {dataset.default_partition_expiration_ms}")
    print()

    if not _sandbox_dataset(dataset):
        raise RuntimeError(
            "dataset is not detected as the 60-day BigQuery Sandbox layout; "
            "do not run the sandbox recovery automatically"
        )

    print("Sandbox policy: keep 60-day table TTL; remove time partitioning from raw finals")
    print("Production partition definitions remain preserved in project metadata.\n")

    plan = load_stage7g_plan()
    repaired = 0
    reused = 0
    pending_upload: list[str] = []

    print("Raw table audit/recovery:")
    for index, raw_item in enumerate(plan["snapshot_tables"], start=1):
        if not isinstance(raw_item, dict):
            raise RuntimeError("invalid Stage 7G plan item")
        source_table = str(raw_item["source_table"])
        target_name = str(raw_item["target_table"]).split(".", 1)[1]
        target_id = f"{args.project}.{args.dataset}.{target_name}"
        expected_rows = int(raw_item["rows"])
        primary_key = tuple(str(value) for value in raw_item["primary_key"])
        designed_partition = TABLE_LAYOUTS[source_table].partition_expression

        final = None
        actual_rows: int | None = None
        try:
            final = client.get_table(target_id)
            actual_rows = _count(client, target_id, args.location)
        except Exception as exc:
            if not _not_found(exc):
                raise

        is_partitioned = final is not None and final.time_partitioning is not None
        if actual_rows == expected_rows and not is_partitioned:
            reused += 1
            print(
                f"  PASS [{index:>2}/26] {source_table:<44} "
                f"rows={actual_rows:>10,} sandbox_layout=UNPARTITIONED"
            )
            continue

        if actual_rows is None:
            status = "MISSING"
        elif is_partitioned:
            status = f"PARTITIONED {actual_rows:,}"
        else:
            status = f"PARTIAL {actual_rows:,}"
        print(
            f"  FIX  [{index:>2}/26] {source_table:<44} "
            f"{status} expected={expected_rows:,}"
        )
        if designed_partition:
            print(f"    production partition design preserved: {designed_partition}")

        recovered_id: str | None = None
        if actual_rows == expected_rows and is_partitioned:
            recovered_id = _snapshot_full_partitioned_final(
                client,
                project=args.project,
                dataset=args.dataset,
                target_name=target_name,
                target_id=target_id,
                expected_rows=expected_rows,
                location=args.location,
            )

        if recovered_id is None:
            recovered_id = _full_current_recovery(
                client,
                args.project,
                args.dataset,
                target_name,
                expected_rows,
                args.location,
            )
        if recovered_id is None:
            recovered_id = _restore_deleted_full_stage(
                client,
                args.project,
                args.dataset,
                target_name,
                expected_rows,
                args.location,
                args.job_limit,
            )
        if recovered_id is None:
            pending_upload.append(source_table)
            print("    no full cloud snapshot found -> local upload still required")
            continue

        _promote_unpartitioned(
            client,
            recovered_id=recovered_id,
            target_id=target_id,
            source_table=source_table,
            primary_key=primary_key,
            expected_rows=expected_rows,
            location=args.location,
        )
        repaired += 1
        print(f"    repaired/promoted: {expected_rows:,} rows, unpartitioned")

    print("\n=== Repair summary ===")
    print(f"Already sandbox-safe finals: {reused}")
    print(f"Recovered/repacked:          {repaired}")
    print(f"Need local upload:           {len(pending_upload)}")
    for source_table in pending_upload:
        print(f"  - {source_table}")

    final_ready = reused + repaired
    print(f"RAW_FINALS_READY={final_ready}/26")
    print("SANDBOX_RAW_LAYOUT=UNPARTITIONED_CLUSTERED")
    if pending_upload:
        print("STAGE7H_SANDBOX_RECOVERY_STATUS=PARTIAL")
    else:
        print("STAGE7H_SANDBOX_RECOVERY_STATUS=PASS")


if __name__ == "__main__":
    main()
