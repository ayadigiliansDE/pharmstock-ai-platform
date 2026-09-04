"""Stage 7I deterministic Kafka CDC micro-batch -> compact Parquet delta."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from pharmstock.cdc import CDC_TOPICS
from pharmstock.rebuild.contracts import SPARK_VERSION, spark_offsets_json, validate_offset_range


def _setting(name: str, default: str = "") -> str:
    value = os.getenv(name, default).strip()
    if not value:
        raise ValueError(f"{name} cannot be empty")
    return value


def _read_offsets(path: Path) -> dict[str, dict[str, int]]:
    decoded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError(f"invalid offset manifest: {path}")
    return {
        str(topic): {str(partition): int(offset) for partition, offset in parts.items()}
        for topic, parts in decoded.items()
    }


def _expected_source_expressions():
    schema_expr = F.lit(None).cast("string")
    table_expr = F.lit(None).cast("string")
    for item in reversed(CDC_TOPICS):
        schema_name, table_name = item.table.split(".", 1)
        schema_expr = F.when(F.col("topic") == item.topic, F.lit(schema_name)).otherwise(
            schema_expr
        )
        table_expr = F.when(F.col("topic") == item.topic, F.lit(table_name)).otherwise(
            table_expr
        )
    return schema_expr, table_expr


def _json_path(raw_col, wrapped: str, schemaless: str):
    return F.coalesce(
        F.get_json_object(raw_col, wrapped),
        F.get_json_object(raw_col, schemaless),
    )


def main() -> None:
    bootstrap = _setting("KAFKA_BOOTSTRAP_SERVERS", "kafka:19092")
    batch_id = _setting("PHARMSTOCK_STAGE7I_BATCH_ID")
    batch_root = Path(_setting("SPARK_STAGE7I_BATCH_ROOT"))
    start_path = Path(_setting("SPARK_STAGE7I_START_OFFSETS"))
    end_path = Path(_setting("SPARK_STAGE7I_END_OFFSETS"))
    start = _read_offsets(start_path)
    end = _read_offsets(end_path)
    expected_records = validate_offset_range(start, end)
    if expected_records <= 0:
        raise ValueError("Stage 7I Spark job requires a non-empty offset range")

    spark = (
        SparkSession.builder.appName(f"pharmstock-stage7i-{batch_id}")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.parquet.compression.codec", "snappy")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    if spark.version != SPARK_VERSION:
        raise RuntimeError(f"Stage 7I requires Spark {SPARK_VERSION}; actual={spark.version}")

    try:
        topics = ",".join(item.topic for item in CDC_TOPICS)
        source = (
            spark.read.format("kafka")
            .option("kafka.bootstrap.servers", bootstrap)
            .option("subscribe", topics)
            .option("startingOffsets", spark_offsets_json(start))
            .option("endingOffsets", spark_offsets_json(end))
            .option("failOnDataLoss", "true")
            .load()
        )

        raw_key = F.col("key").cast("string")
        raw_value = F.col("value").cast("string")
        expected_schema, expected_table = _expected_source_expressions()
        framed = (
            source.select(
                "topic",
                "partition",
                "offset",
                F.col("timestamp").alias("kafka_timestamp"),
                raw_key.alias("key_json"),
                raw_value.alias("raw_value_json"),
            )
            .withColumn("op", _json_path(F.col("raw_value_json"), "$.payload.op", "$.op"))
            .withColumn(
                "source_schema",
                _json_path(
                    F.col("raw_value_json"), "$.payload.source.schema", "$.source.schema"
                ),
            )
            .withColumn(
                "source_table",
                _json_path(
                    F.col("raw_value_json"), "$.payload.source.table", "$.source.table"
                ),
            )
            .withColumn(
                "source_lsn",
                _json_path(
                    F.col("raw_value_json"), "$.payload.source.lsn", "$.source.lsn"
                ).cast("long"),
            )
            .withColumn(
                "source_tx_id",
                _json_path(
                    F.col("raw_value_json"), "$.payload.source.txId", "$.source.txId"
                ).cast("long"),
            )
            .withColumn(
                "source_ts_ms",
                _json_path(
                    F.col("raw_value_json"), "$.payload.source.ts_ms", "$.source.ts_ms"
                ).cast("long"),
            )
            .withColumn(
                "connector_ts_ms",
                _json_path(F.col("raw_value_json"), "$.payload.ts_ms", "$.ts_ms").cast("long"),
            )
            .withColumn(
                "transaction_id",
                _json_path(
                    F.col("raw_value_json"), "$.payload.transaction.id", "$.transaction.id"
                ),
            )
            .withColumn(
                "before_json",
                _json_path(F.col("raw_value_json"), "$.payload.before", "$.before"),
            )
            .withColumn(
                "after_json",
                _json_path(F.col("raw_value_json"), "$.payload.after", "$.after"),
            )
            .withColumn("expected_source_schema", expected_schema)
            .withColumn("expected_source_table", expected_table)
        )

        validation_error = (
            F.when(F.col("raw_value_json").isNull(), F.lit("null_value"))
            .when(F.col("key_json").isNull(), F.lit("null_key"))
            .when(F.col("expected_source_table").isNull(), F.lit("unexpected_topic"))
            .when(~F.col("op").isin("c", "u", "d", "r"), F.lit("unsupported_operation"))
            .when(
                F.col("source_schema") != F.col("expected_source_schema"),
                F.lit("source_schema_topic_mismatch"),
            )
            .when(
                F.col("source_table") != F.col("expected_source_table"),
                F.lit("source_table_topic_mismatch"),
            )
            .when(
                (F.col("op") != "d") & F.col("after_json").isNull(),
                F.lit("missing_after_image"),
            )
        )

        result = (
            framed.withColumn("validation_error", validation_error)
            .withColumn(
                "event_id",
                F.sha2(
                    F.concat_ws(
                        "|",
                        F.col("topic"),
                        F.col("partition").cast("string"),
                        F.col("offset").cast("string"),
                    ),
                    256,
                ),
            )
            .withColumn("batch_id", F.lit(batch_id))
            .withColumn("ingested_at", F.current_timestamp())
            .drop("expected_source_schema", "expected_source_table", "raw_value_json")
            .select(
                "event_id",
                "batch_id",
                "topic",
                "partition",
                "offset",
                "kafka_timestamp",
                "key_json",
                "op",
                "source_schema",
                "source_table",
                "source_lsn",
                "source_tx_id",
                "source_ts_ms",
                "connector_ts_ms",
                "transaction_id",
                "before_json",
                "after_json",
                "ingested_at",
                "validation_error",
            )
        ).persist()

        try:
            total_rows = result.count()
            invalid_rows = result.filter(F.col("validation_error").isNotNull()).count()
            if total_rows != expected_records:
                raise RuntimeError(
                    "Stage 7I offset-range mismatch "
                    f"expected={expected_records} actual={total_rows}"
                )
            if invalid_rows:
                raise RuntimeError(f"Stage 7I CDC validation failures: {invalid_rows}")

            operation_counts = {
                str(row["op"]): int(row["count"])
                for row in result.groupBy("op").count().collect()
                if row["op"] is not None
            }
            table_counts = {
                f"{row['source_schema']}.{row['source_table']}": int(row["count"])
                for row in result.groupBy("source_schema", "source_table").count().collect()
                if row["source_schema"] is not None and row["source_table"] is not None
            }

            events_path = batch_root / "events"
            clean = result.drop("validation_error")
            clean.write.mode("overwrite").option("compression", "snappy").parquet(
                str(events_path)
            )
            summary = {
                "stage": "7I",
                "phase": "spark_microbatch",
                "batch_id": batch_id,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "spark_version": spark.version,
                "expected_offset_range_records": expected_records,
                "rows": total_rows,
                "invalid_rows": invalid_rows,
                "operation_counts": operation_counts,
                "source_table_counts": table_counts,
                "start_offsets": start,
                "end_offsets": end,
                "output_path": str(events_path),
                "output_format": "parquet_snappy",
            }
            (batch_root / "spark_summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (batch_root / "_SPARK_SUCCESS").write_text("PASS\n", encoding="utf-8")
        finally:
            result.unpersist()

        print("=== PharmStock Stage 7I / Spark CDC Micro-batch ===")
        print(f"Batch ID:        {batch_id}")
        print(f"Offset records:  {expected_records:,}")
        print(f"Validated rows:  {total_rows:,}")
        print("STAGE_7I_SPARK_STATUS=PASS")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
