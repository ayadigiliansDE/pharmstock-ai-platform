"""Stage 5A local warehouse export and BigQuery-contract validation.

Reads deterministic Stage 4B Silver Parquet, validates every table against the dependency-light
BigQuery contract, and rewrites Parquet without Hive directory partitioning so ``event_date`` is
materialized inside each file for direct local-file BigQuery load jobs.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pyspark.sql import DataFrame, SparkSession

from pharmstock.warehouse.bigquery_contracts import (
    SPARK_TYPES_BY_BIGQUERY_TYPE,
    TABLE_CONTRACTS,
    BigQueryTableContract,
)

SPARK_VERSION = "4.2.0"


def _setting(name: str, default: str) -> str:
    value = os.getenv(name, default).strip()
    if not value:
        raise ValueError(f"{name} cannot be empty")
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _schema_map(frame: DataFrame) -> dict[str, str]:
    return {field.name: field.dataType.simpleString() for field in frame.schema.fields}


def _validate_schema(frame: DataFrame, contract: BigQueryTableContract) -> dict[str, str]:
    actual = _schema_map(frame)
    expected_names = set(contract.field_names)
    actual_names = set(actual)
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise RuntimeError(
            f"Stage 5A schema mismatch table={contract.table_name}: "
            f"missing={missing} extra={extra}"
        )
    for field in contract.fields:
        accepted = SPARK_TYPES_BY_BIGQUERY_TYPE[field.field_type]
        actual_type = actual[field.name]
        if actual_type not in accepted:
            raise RuntimeError(
                f"Stage 5A type mismatch table={contract.table_name} field={field.name}: "
                f"spark={actual_type} bigquery={field.field_type} accepted={sorted(accepted)}"
            )
    return actual


def _read_silver(spark: SparkSession, silver_root: Path, table_name: str) -> DataFrame:
    table_path = silver_root / table_name
    if not table_path.exists():
        raise FileNotFoundError(f"Stage 5A Silver table is missing: {table_path}")
    return spark.read.option("basePath", str(table_path)).parquet(str(table_path))


def main() -> None:
    silver_root = Path(
        _setting("SPARK_STAGE5A_SILVER", "/opt/pharmstock/artifacts/stage4b/silver")
    )
    output_root = Path(
        _setting("SPARK_STAGE5A_OUTPUT", "/opt/pharmstock/artifacts/stage5a")
    )
    warehouse_root = output_root / "warehouse_ready"
    if not silver_root.exists():
        raise FileNotFoundError(f"Stage 4B Silver input is missing: {silver_root}")

    if warehouse_root.exists():
        shutil.rmtree(warehouse_root)
    (output_root / "spark_export_summary.json").unlink(missing_ok=True)
    (output_root / "_SPARK_SUCCESS").unlink(missing_ok=True)
    warehouse_root.mkdir(parents=True, exist_ok=True)

    spark = (
        SparkSession.builder.appName("pharmstock-stage5a-warehouse-export")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.adaptive.enabled", "true")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    table_summaries: dict[str, dict[str, object]] = {}
    total_rows = 0
    try:
        for table_name, contract in TABLE_CONTRACTS.items():
            source = _read_silver(spark, silver_root, table_name).persist()
            try:
                source_rows = source.count()
                source_unique_ids = source.select("event_id").distinct().count()
                if source_rows != source_unique_ids:
                    raise RuntimeError(
                        f"Stage 5A source table contains duplicate event_id values: {table_name}"
                    )
                source_schema = _validate_schema(source, contract)

                target_path = warehouse_root / table_name
                source.write.mode("overwrite").option("compression", "snappy").parquet(
                    str(target_path)
                )
                exported = spark.read.parquet(str(target_path)).persist()
                try:
                    exported_rows = exported.count()
                    exported_unique_ids = exported.select("event_id").distinct().count()
                    exported_schema = _validate_schema(exported, contract)
                finally:
                    exported.unpersist()

                if exported_rows != source_rows:
                    raise RuntimeError(
                        f"Stage 5A export row mismatch table={table_name}: "
                        f"source={source_rows} exported={exported_rows}"
                    )
                if exported_unique_ids != exported_rows:
                    raise RuntimeError(
                        f"Stage 5A exported table contains duplicate event_id values: {table_name}"
                    )
                if "event_date" not in exported_schema:
                    raise RuntimeError(
                        f"Stage 5A export did not materialize event_date in table={table_name}"
                    )

                total_rows += exported_rows
                table_summaries[table_name] = {
                    "source_rows": source_rows,
                    "exported_rows": exported_rows,
                    "unique_event_ids": exported_unique_ids,
                    "partition_field": contract.partition_field,
                    "clustering_fields": list(contract.clustering_fields),
                    "source_schema": source_schema,
                    "export_schema": exported_schema,
                    "output_path": str(target_path),
                    "event_date_materialized": True,
                }
                print(
                    f"  {table_name:<34} rows={exported_rows:>8,} "
                    f"columns={len(contract.fields):>2}"
                )
            finally:
                source.unpersist()

        summary: dict[str, object] = {
            "stage": "5A",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "spark_version": spark.version,
            "expected_spark_version": SPARK_VERSION,
            "source_layer": "stage4b_silver",
            "output_format": "parquet_snappy",
            "hive_partitioned_output": False,
            "event_date_materialized_in_file": True,
            "table_count": len(table_summaries),
            "total_exported_rows": total_rows,
            "tables": table_summaries,
        }
        _write_json(output_root / "spark_export_summary.json", summary)
        (output_root / "_SPARK_SUCCESS").write_text(
            "STAGE_5A_SPARK_EXPORT_SUCCESS\n", encoding="utf-8"
        )
        print("\n=== PharmStock Stage 5A Warehouse Export ===")
        print(f"Spark version:              {spark.version}")
        print(f"BigQuery-ready tables:      {len(table_summaries)}")
        print(f"Total exported rows:        {total_rows:,}")
        print("event_date in Parquet file: YES")
        print("STAGE_5A_SPARK_STATUS=PASS")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
