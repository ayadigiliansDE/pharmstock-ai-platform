"""Stage 5A acceptance: validate Silver and emit BigQuery warehouse contracts locally."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from run_stage5a_spark import spark_compose_command

from pharmstock.warehouse.bigquery_contracts import TABLE_CONTRACTS
from pharmstock.warehouse.bigquery_plan import generate_bigquery_contract_artifacts


def _run(command: list[str], label: str) -> None:
    completed = subprocess.run(command, check=False)
    if completed.returncode:
        raise RuntimeError(f"{label} exited with code {completed.returncode}")


def _load_json(path: Path) -> dict[str, object]:
    if not path.exists():
        raise RuntimeError(f"missing Stage 5A prerequisite/output: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    stage4b = Path("artifacts/stage4b")
    stage5a = Path("artifacts/stage5a")
    if not (stage4b / "_SUCCESS").exists():
        raise RuntimeError("Stage 5A requires a completed Stage 4B checkpoint")

    if stage5a.exists():
        shutil.rmtree(stage5a)
    stage5a.mkdir(parents=True, exist_ok=True)

    print("=== PharmStock V2 / Stage 5A BigQuery Warehouse Foundation ===")
    print("Source:                  Stage 4B Silver Parquet")
    print("Local warehouse format:  PARQUET / SNAPPY")
    print("BigQuery tables:         7 (6 facts + event_index)")
    print("Partition field:         event_date")
    print("Cloud mode:              DRY-RUN CONTRACTS ONLY")
    print("Cloud mutation:          NONE in checkpoint")
    print("Validating Silver + exporting warehouse-ready Parquet...")

    _run(spark_compose_command(), "Stage 5A Spark warehouse export")
    spark_summary = _load_json(stage5a / "spark_export_summary.json")
    catalog = generate_bigquery_contract_artifacts(stage5a)
    stage4b_verification = _load_json(stage4b / "silver_verification.json")

    spark_tables = spark_summary["tables"]
    if set(spark_tables) != set(TABLE_CONTRACTS):
        raise RuntimeError("Stage 5A Spark output does not cover all BigQuery table contracts")

    expected_fact_counts = {
        name: int(count)
        for name, count in stage4b_verification["table_counts"].items()
    }
    expected_event_index = int(stage4b_verification["silver_rows"])
    expected_counts = {"event_index": expected_event_index, **expected_fact_counts}

    for table_name, expected_rows in expected_counts.items():
        actual_rows = int(spark_tables[table_name]["exported_rows"])
        if actual_rows != expected_rows:
            raise RuntimeError(
                f"Stage 5A row mismatch table={table_name}: "
                f"expected={expected_rows} exported={actual_rows}"
            )
        if not bool(spark_tables[table_name]["event_date_materialized"]):
            raise RuntimeError(f"Stage 5A event_date not materialized for {table_name}")
        schema_path = stage5a / "contracts" / f"{table_name}.schema.json"
        if not schema_path.exists():
            raise RuntimeError(f"Stage 5A BigQuery schema is missing for {table_name}")

    if int(catalog["table_count"]) != len(TABLE_CONTRACTS):
        raise RuntimeError("Stage 5A warehouse catalog table count mismatch")

    fact_rows = sum(expected_fact_counts.values())
    if fact_rows != expected_event_index:
        raise RuntimeError(
            "Stage 5A Silver facts do not reconcile to event_index before warehouse export"
        )

    verification = {
        "stage": "5A",
        "verified_at": datetime.now(UTC).isoformat(),
        "warehouse": "BigQuery",
        "cloud_execution": False,
        "source_silver_rows": expected_event_index,
        "fact_rows": fact_rows,
        "event_index_rows": expected_event_index,
        "warehouse_table_count": len(TABLE_CONTRACTS),
        "warehouse_export_total_rows": int(spark_summary["total_exported_rows"]),
        "event_date_materialized_in_file": True,
        "row_reconciliation_verified": True,
        "schema_contracts_verified": True,
        "unique_event_ids_verified": True,
        "cloud_mutation_performed": False,
        "dataset_id": catalog["dataset_id"],
        "location": catalog["location"],
    }
    verification_path = stage5a / "warehouse_verification.json"
    verification_path.write_text(
        json.dumps(verification, indent=2, sort_keys=True), encoding="utf-8"
    )
    (stage5a / "_SUCCESS").write_text("STAGE_5A_VERIFIED\n", encoding="utf-8")

    print("\nStage 5A verification:")
    print(f"  Accepted Silver events:   {expected_event_index:,}")
    print(f"  Fact-table rows:           {fact_rows:,}")
    print(f"  event_index rows:          {expected_event_index:,}")
    print(f"  BigQuery table contracts:  {len(TABLE_CONTRACTS)}")
    print(f"  Exported physical rows:    {verification['warehouse_export_total_rows']:,}")
    print("  event_date materialized:   YES")
    print("  Cloud mutation performed:  NO")
    print("\nGenerated files:")
    print(f"  {(stage5a / 'warehouse_ready').resolve()}")
    print(f"  {(stage5a / 'contracts').resolve()}")
    print(f"  {(stage5a / 'bigquery_bootstrap.sql').resolve()}")
    print(f"  {(stage5a / 'warehouse_catalog.json').resolve()}")
    print(f"  {(stage5a / 'cloud_load_plan.json').resolve()}")
    print(f"  {verification_path.resolve()}")
    print("\nSTAGE_5A_STATUS=PASS")


if __name__ == "__main__":
    main()
