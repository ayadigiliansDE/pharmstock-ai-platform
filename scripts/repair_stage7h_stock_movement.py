"""Recover and safely promote the deleted Stage 7H stock_movement staging table.

This repair uses the final successful BigQuery load job to discover the deleted
staging table and a point-in-time snapshot, restores that snapshot, validates
its row count and primary key uniqueness, then recreates the intended final
Stage 7H table using the project's canonical promotion SQL.
"""

from __future__ import annotations

import argparse
import os
from datetime import UTC

from google.cloud import bigquery

from pharmstock.rebuild.bigquery_stage import (
    atomic_replace_sql,
    duplicate_primary_key_sql,
    load_stage7g_plan,
)

DEFAULT_PROJECT = "pharmstock-ai-platform-2026"
DEFAULT_DATASET = "pharmstock_ops_rebuild"
DEFAULT_LOCATION = "EU"
DEFAULT_JOB_ID = "90c41dc6-f6e1-433c-988b-f90dec965323"
SOURCE_TABLE = "inventory.stock_movement"
EXPECTED_ROWS = 6_844_006


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recover Stage 7H stock_movement")
    parser.add_argument(
        "--project",
        default=os.getenv("PHARMSTOCK_BQ_PROJECT", DEFAULT_PROJECT),
    )
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--location", default=DEFAULT_LOCATION)
    parser.add_argument("--job-id", default=DEFAULT_JOB_ID)
    return parser


def _scalar(client: bigquery.Client, sql: str, location: str) -> int:
    rows = list(client.query(sql, location=location).result())
    if len(rows) != 1:
        raise RuntimeError("expected one scalar result")
    return int(rows[0][0])


def _count(client: bigquery.Client, table_id: str, location: str) -> int:
    return _scalar(client, f"SELECT COUNT(*) FROM `{table_id}`", location)


def _plan_item() -> dict[str, object]:
    plan = load_stage7g_plan()
    for raw_item in plan["snapshot_tables"]:
        if isinstance(raw_item, dict) and raw_item.get("source_table") == SOURCE_TABLE:
            return raw_item
    raise RuntimeError(f"Stage 7G plan does not contain {SOURCE_TABLE}")


def main() -> None:
    args = _parser().parse_args()
    client = bigquery.Client(project=args.project, location=args.location)
    item = _plan_item()
    expected_rows = int(item["rows"])
    if expected_rows != EXPECTED_ROWS:
        raise RuntimeError(
            f"unexpected Stage 7G row count: {expected_rows:,} != {EXPECTED_ROWS:,}"
        )

    job = client.get_job(args.job_id, location=args.location)
    if job.destination is None:
        raise RuntimeError("load job has no destination table")
    if job.ended is None:
        job.reload()
    if job.ended is None:
        raise RuntimeError("load job has no completion timestamp")

    stage_id = (
        f"{job.destination.project}.{job.destination.dataset_id}."
        f"{job.destination.table_id}"
    )
    if job.destination.dataset_id != args.dataset:
        raise RuntimeError(
            f"unexpected staging dataset: {job.destination.dataset_id} != {args.dataset}"
        )
    if "stock_movement" not in job.destination.table_id:
        raise RuntimeError(f"unexpected staging table from load job: {stage_id}")

    snapshot_ms = int(job.ended.astimezone(UTC).timestamp() * 1000)
    snapshot_id = f"{stage_id}@{snapshot_ms}"
    recovered_id = (
        f"{args.project}.{args.dataset}."
        "__recovered_stage7h_inventory__stock_movement"
    )
    target_name = str(item["target_table"]).split(".", 1)[1]
    target_id = f"{args.project}.{args.dataset}.{target_name}"
    primary_key = tuple(str(value) for value in item["primary_key"])

    print("=== Stage 7H stock_movement recovery ===")
    print(f"Deleted staging:      {stage_id}")
    print(f"Snapshot epoch ms:    {snapshot_ms}")
    print(f"Recovered staging:    {recovered_id}")
    print(f"Final target:         {target_id}")
    print(f"Expected rows:        {expected_rows:,}")

    reuse_recovered = False
    try:
        recovered_rows = _count(client, recovered_id, args.location)
        if recovered_rows == expected_rows:
            reuse_recovered = True
            print(f"Recovered table:      REUSE ({recovered_rows:,} rows)")
        else:
            print(
                "Recovered table:      INVALID existing copy "
                f"({recovered_rows:,} rows); recreating"
            )
            client.delete_table(recovered_id, not_found_ok=True)
    except Exception as exc:
        if exc.__class__.__name__ != "NotFound" and getattr(exc, "code", None) != 404:
            raise

    if not reuse_recovered:
        print("Restore deleted stage: START")
        copy_job = client.copy_table(snapshot_id, recovered_id, location=args.location)
        print(f"Restore job:          {copy_job.job_id}")
        copy_job.result()
        recovered_rows = _count(client, recovered_id, args.location)
        print(f"Recovered row count:  {recovered_rows:,}")
        if recovered_rows != expected_rows:
            raise RuntimeError(
                "restored staging row count mismatch; recovered table preserved: "
                f"{recovered_rows:,} != {expected_rows:,} at {recovered_id}"
            )

    duplicates = _scalar(
        client,
        duplicate_primary_key_sql(recovered_id, primary_key),
        args.location,
    )
    print(f"Duplicate PK groups:  {duplicates:,}")
    if duplicates:
        raise RuntimeError(
            f"recovered staging has duplicate primary keys; preserved at {recovered_id}"
        )

    # The existing final is known to be partial. Once the recovered full stage is
    # validated, deleting it before promotion reduces peak storage safely.
    client.delete_table(target_id, not_found_ok=True)
    print("Partial final removed: YES")

    client.query(
        atomic_replace_sql(
            target_table_id=target_id,
            staging_table_id=recovered_id,
            source_table=SOURCE_TABLE,
        ),
        location=args.location,
    ).result()

    final_rows = _count(client, target_id, args.location)
    print(f"Final real row count: {final_rows:,}")
    if final_rows != expected_rows:
        raise RuntimeError(
            "promotion row count mismatch; recovered staging PRESERVED: "
            f"{final_rows:,} != {expected_rows:,} at {recovered_id}"
        )

    final = client.get_table(target_id)
    final.description = f"PharmStock Stage 7H rebuild of {SOURCE_TABLE}"
    final.labels = {
        "platform": "pharmstock",
        "stage": "7h",
        "layer": "rebuild_raw",
    }
    client.update_table(final, ["description", "labels"])

    client.delete_table(recovered_id, not_found_ok=True)
    print("Recovered staging:    DELETED AFTER VERIFIED PROMOTION")
    print("STOCK_MOVEMENT_REPAIR_STATUS=PASS")


if __name__ == "__main__":
    main()
