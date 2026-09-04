"""Explicit Stage 7H BigQuery rebuild deployment followed by dbt analytics build.

v0.29.5 adds BigQuery Sandbox-safe physical layout:
- detects the sandbox 60-day expiration policy without trying to disable it;
- materializes raw finals unpartitioned in sandbox so old historical partitions
  are not deleted immediately by the 60-day partition TTL;
- keeps production partition metadata in TABLE_LAYOUTS for billing-enabled mode;
- verifies staging, reused, and promoted row counts with real COUNT(*) queries;
- preserves a fully validated staging table if promotion/final verification fails;
- keeps the one-table-at-a-time storage-safe strategy and per-file progress output.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pharmstock.rebuild.bigquery_stage import (
    STAGE7H_GOLD_MODELS,
    STAGE7H_ROOT,
    TABLE_LAYOUTS,
    Stage7HConfig,
    atomic_replace_sql,
    build_preflight,
    config_from_environment,
    duplicate_primary_key_sql,
    load_stage7g_plan,
    parquet_files,
)


def _parser() -> argparse.ArgumentParser:
    defaults = config_from_environment()
    parser = argparse.ArgumentParser(description="Deploy Stage 7G rebuild to BigQuery and run dbt")
    parser.add_argument("--project", default=defaults.project_id)
    parser.add_argument("--dataset", default=defaults.dataset_id)
    parser.add_argument("--location", default=defaults.location)
    parser.add_argument("--dbt-base-dataset", default=defaults.dbt_base_dataset)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument(
        "--force-reload",
        action="store_true",
        help="Reload even Stage 7H final tables that already match the expected row count.",
    )
    return parser


def _dbt_executable() -> str | None:
    executable = "dbt.exe" if os.name == "nt" else "dbt"
    beside_python = Path(sys.executable).parent / executable
    if beside_python.is_file():
        return str(beside_python)
    return shutil.which("dbt")


def _scalar(client: object, sql: str, location: str) -> int:
    rows = list(client.query(sql, location=location).result())
    if len(rows) != 1:
        raise RuntimeError("expected a single BigQuery scalar result")
    return int(rows[0][0])


def _table_row_count(client: object, table_id: str, location: str) -> int:
    return _scalar(client, f"SELECT COUNT(*) FROM `{table_id}`", location)


SANDBOX_TTL_MS = 60 * 24 * 60 * 60 * 1000


def _is_sandbox_dataset(dataset: object) -> bool:
    override = os.getenv("PHARMSTOCK_BQ_SANDBOX", "auto").strip().lower()
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False
    table_ttl = getattr(dataset, "default_table_expiration_ms", None)
    partition_ttl = getattr(dataset, "default_partition_expiration_ms", None)
    return table_ttl == SANDBOX_TTL_MS and partition_ttl == SANDBOX_TTL_MS


def _ensure_dataset(client: object, bigquery: object, config: Stage7HConfig) -> bool:
    dataset_id = f"{config.project_id}.{config.dataset_id}"
    dataset = bigquery.Dataset(dataset_id)
    dataset.location = config.location
    dataset.description = "PharmStock Stage 7H production-like operational rebuild"
    dataset.labels = {"platform": "pharmstock", "stage": "7h", "layer": "rebuild_raw"}
    client.create_dataset(dataset, exists_ok=True, timeout=30)
    actual = client.get_dataset(dataset_id)
    if actual.location.upper() != config.location.upper():
        raise RuntimeError(
            "BigQuery dataset location mismatch: "
            f"expected={config.location} actual={actual.location}"
        )

    sandbox_mode = _is_sandbox_dataset(actual)
    if sandbox_mode:
        print(
            "  BigQuery mode: SANDBOX SAFE "
            "(60-day table TTL retained; raw finals unpartitioned)",
            flush=True,
        )
        return True

    changed: list[str] = []
    if actual.default_table_expiration_ms is not None:
        actual.default_table_expiration_ms = None
        changed.append("default_table_expiration_ms")
    if actual.default_partition_expiration_ms is not None:
        actual.default_partition_expiration_ms = None
        changed.append("default_partition_expiration_ms")
    if changed:
        client.update_dataset(actual, changed)
        print(
            "  dataset expiration defaults: DISABLED "
            f"({', '.join(changed)})",
            flush=True,
        )
    return False


def _clear_table_expiration(
    client: object,
    table_id: str,
    location: str,
    *,
    sandbox_mode: bool,
) -> None:
    if sandbox_mode:
        return
    table = client.get_table(table_id)
    options = ["expiration_timestamp = NULL"]
    if table.time_partitioning is not None:
        options.append("partition_expiration_days = NULL")
    sql = f"ALTER TABLE `{table_id}` SET OPTIONS ({', '.join(options)})"
    client.query(sql, location=location).result()


def _human_mib(size_bytes: int) -> str:
    return f"{size_bytes / (1024 * 1024):,.1f} MiB"


def _load_staging_table(
    *,
    client: object,
    bigquery: object,
    staging_table_id: str,
    source_table: str,
    files: tuple[Path, ...],
    expected_rows: int,
    location: str,
) -> int:
    if not files and expected_rows:
        raise RuntimeError(f"no Parquet files available for {staging_table_id}")
    client.delete_table(staging_table_id, not_found_ok=True)
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
        with path.open("rb") as handle:
            job = client.load_table_from_file(
                handle,
                staging_table_id,
                job_config=config,
                location=location,
            )
            print(
                f"    upload {source_table:<38} "
                f"file={index:>2}/{total_files:<2} size={_human_mib(path.stat().st_size):>11} "
                f"job={job.job_id}",
                flush=True,
            )
            job.result()
    if expected_rows == 0:
        return 0
    return _table_row_count(client, staging_table_id, location)


def _run_dbt(dbt: str, args: list[str], env: dict[str, str]) -> None:
    command = [
        dbt,
        *args,
        "--project-dir",
        "dbt/pharmstock_analytics",
        "--profiles-dir",
        "dbt/profiles",
    ]
    result = subprocess.run(command, env=env, check=False)
    if result.returncode:
        raise RuntimeError(f"dbt command failed with code {result.returncode}: {' '.join(args)}")


def _verify_gold(client: object, config: Stage7HConfig) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    assert config.project_id is not None
    for model in STAGE7H_GOLD_MODELS:
        table_id = f"{config.project_id}.{config.dbt_gold_dataset}.{model}"
        table = client.get_table(table_id)
        rows = int(table.num_rows)
        if rows <= 0:
            raise RuntimeError(f"Stage 7H dbt Gold model is empty: {table_id}")
        result.append({"model": model, "table_id": table_id, "rows": rows})
    return result


def _existing_stage7h_final(
    client: object,
    target_id: str,
    expected_rows: int,
    location: str,
    *,
    sandbox_mode: bool,
) -> bool:
    try:
        table = client.get_table(target_id)
    except Exception as exc:  # google NotFound is optional at import time
        if exc.__class__.__name__ == "NotFound" or getattr(exc, "code", None) == 404:
            return False
        raise

    if sandbox_mode:
        if table.time_partitioning is not None:
            return False
    else:
        labels = table.labels or {}
        labels_match = (
            labels.get("platform") == "pharmstock"
            and labels.get("stage") == "7h"
            and labels.get("layer") == "rebuild_raw"
        )
        if not labels_match:
            return False
        _clear_table_expiration(
            client, target_id, location, sandbox_mode=sandbox_mode
        )
    return _table_row_count(client, target_id, location) == expected_rows


def _promoted_item(
    *,
    item: dict[str, object],
    source_table: str,
    target_id: str,
    sandbox_mode: bool,
) -> dict[str, object]:
    layout = TABLE_LAYOUTS[source_table]
    return {
        **item,
        "table_id": target_id,
        "partition_expression": None if sandbox_mode else layout.partition_expression,
        "production_partition_expression": layout.partition_expression,
        "clustering_fields": list(layout.clustering_fields),
    }


def _execute(config: Stage7HConfig, *, force_reload: bool = False) -> dict[str, object]:
    try:
        import google.auth
        from google.cloud import bigquery
    except ImportError as exc:
        raise RuntimeError(
            'Install cloud dependencies with: pip install -e ".[gcp,analytics]"'
        ) from exc

    if config.project_id is None:
        raise RuntimeError("Stage 7H cloud execution requires a real GCP project ID")
    credentials, adc_project = google.auth.default()
    client = bigquery.Client(
        project=config.project_id,
        credentials=credentials,
        location=config.location,
    )
    sandbox_mode = _ensure_dataset(client, bigquery, config)

    plan = load_stage7g_plan()
    promoted: list[dict[str, object]] = []
    reused_count = 0
    reloaded_count = 0

    print("\nResume/storage-safe raw rebuild:")
    print("  strategy: reuse matching finals + stage/promote/delete one table at a time")

    for table_index, raw_item in enumerate(plan["snapshot_tables"], start=1):
        assert isinstance(raw_item, dict)
        source_table = str(raw_item["source_table"])
        target_name = str(raw_item["target_table"]).split(".", 1)[1]
        target_id = f"{config.project_id}.{config.dataset_id}.{target_name}"
        expected_rows = int(raw_item["rows"])
        primary_key = tuple(str(value) for value in raw_item["primary_key"])
        files = parquet_files(Path(str(raw_item["local_parquet_path"])))
        item: dict[str, object] = {
            "source_table": source_table,
            "target_table": target_name,
            "rows": expected_rows,
            "parquet_files": len(files),
            "primary_key": list(primary_key),
        }

        if not force_reload and _existing_stage7h_final(
            client,
            target_id,
            expected_rows,
            config.location,
            sandbox_mode=sandbox_mode,
        ):
            promoted.append(
                _promoted_item(
                    item=item,
                    source_table=source_table,
                    target_id=target_id,
                    sandbox_mode=sandbox_mode,
                )
            )
            reused_count += 1
            print(
                f"  resume   [{table_index:>2}/{len(plan['snapshot_tables'])}] "
                f"{source_table:<44} rows={expected_rows:>10,} (already promoted)",
                flush=True,
            )
            continue

        stage_name = f"__stage7h_{target_name}_{uuid4().hex[:10]}"
        stage_id = f"{config.project_id}.{config.dataset_id}.{stage_name}"
        # Preserve a fully validated stage if promotion fails; partial/invalid stages are cleaned.
        stage_verified = False
        promotion_complete = False
        try:
            print(
                f"  stage    [{table_index:>2}/{len(plan['snapshot_tables'])}] "
                f"{source_table:<44} files={len(files):>2} rows={expected_rows:>10,}",
                flush=True,
            )
            actual_rows = _load_staging_table(
                client=client,
                bigquery=bigquery,
                staging_table_id=stage_id,
                source_table=source_table,
                files=files,
                expected_rows=expected_rows,
                location=config.location,
            )
            if actual_rows != expected_rows:
                raise RuntimeError(
                    f"{source_table}: staged row count {actual_rows} != expected {expected_rows}"
                )
            duplicates = _scalar(
                client,
                duplicate_primary_key_sql(stage_id, primary_key),
                config.location,
            )
            if duplicates:
                raise RuntimeError(f"{source_table}: duplicate primary keys detected")
            stage_verified = True

            client.query(
                atomic_replace_sql(
                    target_table_id=target_id,
                    staging_table_id=stage_id,
                    source_table=source_table,
                    partitioning_enabled=not sandbox_mode,
                ),
                location=config.location,
            ).result()
            final_rows = _table_row_count(client, target_id, config.location)
            if final_rows != expected_rows:
                raise RuntimeError(
                    f"{source_table}: promoted row count {final_rows} != {expected_rows}; "
                    f"validated staging preserved at {stage_id}"
                )
            _clear_table_expiration(
                client,
                target_id,
                config.location,
                sandbox_mode=sandbox_mode,
            )
            final = client.get_table(target_id)
            if sandbox_mode and final.time_partitioning is not None:
                raise RuntimeError(
                    f"{source_table}: sandbox final must be unpartitioned"
                )
            if not sandbox_mode:
                final.description = f"PharmStock Stage 7H rebuild of {source_table}"
                final.labels = {
                    "platform": "pharmstock",
                    "stage": "7h",
                    "layer": "rebuild_raw",
                }
                client.update_table(final, ["description", "labels"])
            promotion_complete = True
            promoted.append(
                _promoted_item(
                    item=item,
                    source_table=source_table,
                    target_id=target_id,
                    sandbox_mode=sandbox_mode,
                )
            )
            reloaded_count += 1
            print(
                f"  promoted [{table_index:>2}/{len(plan['snapshot_tables'])}] "
                f"{source_table:<44} rows={expected_rows:>10,}",
                flush=True,
            )
        finally:
            if promotion_complete or not stage_verified:
                client.delete_table(stage_id, not_found_ok=True)
            else:
                print(
                    f"  PRESERVED_STAGE={stage_id} (validated; promotion needs repair/retry)",
                    flush=True,
                )

    dbt = _dbt_executable()
    if dbt is None:
        raise RuntimeError('dbt is required; install with: pip install -e ".[analytics]"')
    env = os.environ.copy()
    env.update(
        {
            "PHARMSTOCK_BQ_PROJECT": config.project_id,
            "PHARMSTOCK_BQ_LOCATION": config.location,
            "PHARMSTOCK_BQ_REBUILD_DATASET": config.dataset_id,
            "PHARMSTOCK_DBT_BASE_DATASET": config.dbt_base_dataset,
        }
    )
    print("\nRunning dbt Stage 7H rebuild analytics...")
    _run_dbt(dbt, ["debug"], env)
    _run_dbt(dbt, ["build", "--select", "tag:stage7h", "--fail-fast"], env)
    gold = _verify_gold(client, config)

    return {
        "stage": "7H",
        "status": "PASS",
        "executed_at": datetime.now(UTC).isoformat(),
        "cloud_mutation": True,
        "project_id": config.project_id,
        "adc_project": adc_project,
        "location": config.location,
        "raw_dataset": config.dataset_id,
        "dbt_staging_dataset": config.dbt_staging_dataset,
        "dbt_gold_dataset": config.dbt_gold_dataset,
        "gold_models": gold,
        "raw_table_count": len(promoted),
        "raw_total_rows": sum(int(item["rows"]) for item in promoted),
        "raw_tables": promoted,
        "resume_reused_tables": reused_count,
        "resume_reloaded_tables": reloaded_count,
        "historical_replay_through_kafka": False,
        "cdc_resume_offsets_preserved": True,
        "bigquery_sandbox_mode": sandbox_mode,
        "raw_partitioning_enabled": not sandbox_mode,
    }


def main() -> None:
    args = _parser().parse_args()
    config = Stage7HConfig(args.project, args.dataset, args.location, args.dbt_base_dataset)
    preflight = build_preflight(config=config)

    print("=== PharmStock V2 / Stage 7H BigQuery + dbt Cloud Deployment ===")
    print(f"Project:                 {config.project_id or 'NOT SET'}")
    print(f"Raw dataset:             {config.dataset_id}")
    print(f"dbt staging dataset:     {config.dbt_staging_dataset}")
    print(f"dbt Gold dataset:        {config.dbt_gold_dataset}")
    print(f"Location:                {config.location}")
    print(f"Raw tables:              {preflight['snapshot_table_count']}")
    print(f"Expected raw rows:       {preflight['expected_snapshot_rows']:,}")
    print("Historical Kafka replay: NO")

    if not args.execute:
        print("Cloud mutation:          NO / DRY RUN")
        print("\nSTAGE_7H_CLOUD_MODE=DRY_RUN")
        return
    if not args.replace:
        raise SystemExit("Cloud execution requires --replace to make replacement explicit")
    if not config.project_configured:
        raise SystemExit("Set --project or PHARMSTOCK_BQ_PROJECT before Stage 7H cloud execution")
    if not preflight["cloud_ready_hint"]:
        raise SystemExit(
            "Stage 7H cloud preconditions are incomplete; "
            "run checkpoint 7h and inspect preflight.json"
        )

    print("Cloud mutation:          YES")
    print(f"Force reload:            {'YES' if args.force_reload else 'NO / RESUME SAFE'}")
    report = _execute(config, force_reload=args.force_reload)
    STAGE7H_ROOT.mkdir(parents=True, exist_ok=True)
    (STAGE7H_ROOT / "cloud_execution_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    (STAGE7H_ROOT / "_CLOUD_SUCCESS").write_text("PASS\n", encoding="utf-8")
    (STAGE7H_ROOT / "_SUCCESS").write_text("PASS\n", encoding="utf-8")

    print("\nStage 7H verification:")
    print(f"  BigQuery raw tables:       {report['raw_table_count']}")
    print(f"  BigQuery raw rows:         {report['raw_total_rows']:,}")
    print(f"  Resume reused tables:      {report['resume_reused_tables']}")
    print(f"  Resume reloaded tables:    {report['resume_reloaded_tables']}")
    print(f"  dbt Gold models:           {len(report['gold_models'])}")
    print("  Row-count validation:      PASS")
    print("  Primary-key validation:    PASS")
    print("  dbt build:                 PASS")
    print("  Historical Kafka replay:   NO")
    print("  CDC resume offsets:        PRESERVED")
    print("\nSTAGE_7H_STATUS=PASS")


if __name__ == "__main__":
    main()
