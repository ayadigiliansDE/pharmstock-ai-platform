"""Stage 7G controlled large-scale PostgreSQL historical snapshot via Spark JDBC."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from pharmstock.rebuild.contracts import (
    HASH_PARTITION_UPPER_BOUND,
    POSTGRES_JDBC_DRIVER,
    POSTGRES_JDBC_URL,
    POSTGRES_REBUILD_USER,
    SNAPSHOT_TABLES,
    SPARK_VERSION,
)


def _setting(name: str, default: str = "") -> str:
    value = os.getenv(name, default).strip()
    if not value:
        raise ValueError(f"{name} cannot be empty")
    return value


def _partitioned_dbtable(source_table: str, primary_key: tuple[str, ...]) -> str:
    parts = ", ".join(f"t.{column}::text" for column in primary_key)
    return (
        "(SELECT t.*, "
        f"((hashtextextended(concat_ws('|', {parts}), 0) & "
        f"{HASH_PARTITION_UPPER_BOUND}::bigint))::bigint AS __stage7g_partition_key "
        f"FROM {source_table} AS t) AS stage7g_source"
    )


def _read_table(
    spark: SparkSession,
    *,
    source_table: str,
    primary_key: tuple[str, ...],
    partitions: int,
    jdbc_url: str,
    user: str,
    password: str,
):
    reader = (
        spark.read.format("jdbc")
        .option("url", jdbc_url)
        .option("user", user)
        .option("password", password)
        .option("driver", POSTGRES_JDBC_DRIVER)
        .option("fetchsize", "5000")
    )
    if partitions <= 1:
        return reader.option("dbtable", source_table).load()
    return (
        reader.option("dbtable", _partitioned_dbtable(source_table, primary_key))
        .option("partitionColumn", "__stage7g_partition_key")
        .option("lowerBound", "0")
        .option("upperBound", str(HASH_PARTITION_UPPER_BOUND))
        .option("numPartitions", str(partitions))
        .load()
        .drop("__stage7g_partition_key")
    )


def main() -> None:
    output_root = Path(_setting("SPARK_STAGE7G_OUTPUT", "/opt/pharmstock/artifacts/stage7g"))
    jdbc_url = _setting("SPARK_STAGE7G_JDBC_URL", POSTGRES_JDBC_URL)
    jdbc_user = _setting("SPARK_STAGE7G_JDBC_USER", POSTGRES_REBUILD_USER)
    jdbc_password = _setting("SPARK_STAGE7G_JDBC_PASSWORD")

    spark = (
        SparkSession.builder.appName("pharmstock-stage7g-snapshot")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.parquet.compression.codec", "snappy")
        .config("spark.hadoop.parquet.block.size", "67108864")
        .config("spark.sql.files.maxRecordsPerFile", "250000")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    if spark.version != SPARK_VERSION:
        raise RuntimeError(f"Stage 7G requires Spark {SPARK_VERSION}; actual={spark.version}")

    history_root = output_root / "history"
    history_root.mkdir(parents=True, exist_ok=True)
    summaries: dict[str, dict[str, object]] = {}
    total_rows = 0

    try:
        print("=== PharmStock Stage 7G / PostgreSQL Historical Snapshot ===")
        print(f"Spark version:     {spark.version}")
        print(f"Snapshot tables:   {len(SNAPSHOT_TABLES)}")
        print("Output:            Parquet/Snappy")

        for spec in SNAPSHOT_TABLES:
            target_path = output_root / spec.artifact_path
            frame = _read_table(
                spark,
                source_table=spec.source_table,
                primary_key=spec.primary_key,
                partitions=spec.jdbc_partitions,
                jdbc_url=jdbc_url,
                user=jdbc_user,
                password=jdbc_password,
            )
            frame.write.mode("overwrite").option("compression", "snappy").parquet(
                str(target_path)
            )

            exported = spark.read.parquet(str(target_path))
            null_pk = F.lit(False)
            for column in spec.primary_key:
                null_pk = null_pk | F.col(column).isNull()
            metrics = exported.agg(
                F.count(F.lit(1)).alias("rows"),
                F.sum(F.when(null_pk, F.lit(1)).otherwise(F.lit(0))).alias("null_pk_rows"),
            ).first()
            rows = int(metrics["rows"] or 0)
            null_pk_rows = int(metrics["null_pk_rows"] or 0)
            if null_pk_rows:
                raise RuntimeError(
                    f"Stage 7G snapshot primary-key NULLs table={spec.source_table}: "
                    f"{null_pk_rows}"
                )

            total_rows += rows
            summaries[spec.source_table] = {
                "source_table": spec.source_table,
                "primary_key": list(spec.primary_key),
                "jdbc_partitions": spec.jdbc_partitions,
                "category": spec.category,
                "cdc_managed": spec.cdc_managed,
                "rows": rows,
                "columns": len(exported.columns),
                "null_primary_key_rows": null_pk_rows,
                "schema_json": exported.schema.jsonValue(),
                "output_path": str(target_path),
                "bigquery_table": spec.bigquery_table,
            }
            print(f"  {spec.source_table:<42} rows={rows:>10,}")

        summary = {
            "stage": "7G",
            "phase": "historical_snapshot",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "spark_version": spark.version,
            "table_count": len(summaries),
            "total_rows": total_rows,
            "output_format": "parquet_snappy",
            "tables": summaries,
        }
        (output_root / "snapshot_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (output_root / "_SNAPSHOT_SUCCESS").write_text("PASS\n", encoding="utf-8")
        print(f"Total snapshot rows: {total_rows:,}")
        print("STAGE_7G_SNAPSHOT_STATUS=PASS")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
