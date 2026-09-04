"""Stage 7G deterministic Kafka CDC catch-up over an explicit offset range."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from functools import reduce
from pathlib import Path

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window

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
    output_root = Path(_setting("SPARK_STAGE7G_OUTPUT", "/opt/pharmstock/artifacts/stage7g"))
    bootstrap = _setting("KAFKA_BOOTSTRAP_SERVERS", "kafka:19092")
    start_path = Path(
        _setting(
            "SPARK_STAGE7G_START_OFFSETS",
            "/opt/pharmstock/artifacts/stage7g/cutover_start_offsets.json",
        )
    )
    end_path = Path(
        _setting(
            "SPARK_STAGE7G_END_OFFSETS",
            "/opt/pharmstock/artifacts/stage7g/cutover_end_offsets.json",
        )
    )
    start = _read_offsets(start_path)
    end = _read_offsets(end_path)
    expected_records = validate_offset_range(start, end)

    spark = (
        SparkSession.builder.appName("pharmstock-stage7g-cdc-catchup")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.parquet.compression.codec", "snappy")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    if spark.version != SPARK_VERSION:
        raise RuntimeError(f"Stage 7G requires Spark {SPARK_VERSION}; actual={spark.version}")

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
                raw_key.alias("raw_key_json"),
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
                _json_path(F.col("raw_value_json"), "$.payload.source.lsn", "$.source.lsn").cast(
                    "long"
                ),
            )
            .withColumn(
                "source_tx_id",
                _json_path(F.col("raw_value_json"), "$.payload.source.txId", "$.source.txId").cast(
                    "long"
                ),
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
        )
        result = framed.withColumn("validation_error", validation_error).drop(
            "expected_source_schema", "expected_source_table"
        )
        result = result.persist()
        try:
            total_rows = result.count()
            invalid_rows = result.filter(F.col("validation_error").isNotNull()).count()
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
            if total_rows != expected_records:
                raise RuntimeError(
                    f"Stage 7G CDC range mismatch expected={expected_records} actual={total_rows}"
                )
            if invalid_rows:
                raise RuntimeError(f"Stage 7G CDC validation failures: {invalid_rows}")

            target = output_root / "cdc_catchup"
            result.write.mode("overwrite").option("compression", "snappy").parquet(str(target))

            # Reconcile only CDC-managed tables that changed during the historical snapshot.
            # Unchanged tables continue to reference the original snapshot without duplicating
            # multi-million-row Parquet datasets. For each key, Kafka preserves order within
            # its partition, so the latest Debezium event is sufficient to update the snapshot.
            from pharmstock.rebuild.contracts import SNAPSHOT_TABLE_BY_NAME

            reconciled_tables: dict[str, dict[str, object]] = {}
            for source_table, change_count in sorted(table_counts.items()):
                spec = SNAPSHOT_TABLE_BY_NAME.get(source_table)
                if spec is None or not spec.cdc_managed or change_count <= 0:
                    continue
                base_path = output_root / spec.artifact_path
                base = spark.read.parquet(str(base_path))
                table_events = result.filter(
                    (F.col("source_schema") == spec.schema_name)
                    & (F.col("source_table") == spec.table_name)
                )
                after_record = F.from_json(F.col("after_json"), base.schema)
                before_record = F.from_json(F.col("before_json"), base.schema)
                keyed = table_events.withColumn("after_record", after_record).withColumn(
                    "before_record", before_record
                )
                key_columns: list[str] = []
                for primary_key in spec.primary_key:
                    key_name = f"__key_{primary_key}"
                    keyed = keyed.withColumn(
                        key_name,
                        F.coalesce(
                            F.col(f"after_record.{primary_key}"),
                            F.col(f"before_record.{primary_key}"),
                        ),
                    )
                    key_columns.append(key_name)
                missing_keys = keyed.filter(
                    reduce(
                        lambda left, right: left | right,
                        (F.col(name).isNull() for name in key_columns),
                    )
                ).count()
                if missing_keys:
                    raise RuntimeError(
                        f"Stage 7G CDC reconciliation missing primary key "
                        f"table={source_table} rows={missing_keys}"
                    )

                window = Window.partitionBy(*key_columns).orderBy(
                    F.col("source_lsn").desc_nulls_last(),
                    F.col("partition").desc(),
                    F.col("offset").desc(),
                )
                latest = keyed.withColumn("__rn", F.row_number().over(window)).filter(
                    F.col("__rn") == 1
                )
                changed_keys = latest.select(
                    *[
                        F.col(key_name).alias(primary_key)
                        for key_name, primary_key in zip(key_columns, spec.primary_key, strict=True)
                    ]
                )
                retained = base.join(changed_keys, list(spec.primary_key), "left_anti")
                upserts = latest.filter(F.col("op") != "d").select("after_record.*")
                null_upserts = upserts.filter(
                    reduce(
                        lambda left, right: left | right,
                        (F.col(name).isNull() for name in spec.primary_key),
                    )
                ).count()
                if null_upserts:
                    raise RuntimeError(
                        f"Stage 7G CDC reconciliation invalid upsert "
                        f"table={source_table} rows={null_upserts}"
                    )
                reconciled = retained.unionByName(upserts)
                reconciled_path = output_root / "reconciled" / spec.schema_name / spec.table_name
                reconciled.write.mode("overwrite").option("compression", "snappy").parquet(
                    str(reconciled_path)
                )
                reconciled_rows = spark.read.parquet(str(reconciled_path)).count()
                reconciled_tables[source_table] = {
                    "change_events": change_count,
                    "rows": reconciled_rows,
                    "output_path": str(reconciled_path),
                    "primary_key": list(spec.primary_key),
                }

            summary = {
                "stage": "7G",
                "phase": "cdc_catchup",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "spark_version": spark.version,
                "expected_offset_range_records": expected_records,
                "rows": total_rows,
                "invalid_rows": invalid_rows,
                "operation_counts": operation_counts,
                "source_table_counts": table_counts,
                "reconciled_tables": reconciled_tables,
                "start_offsets": start,
                "end_offsets": end,
                "output_path": str(target),
                "output_format": "parquet_snappy",
            }
            (output_root / "cdc_catchup_summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (output_root / "_CDC_CATCHUP_SUCCESS").write_text("PASS\n", encoding="utf-8")
        finally:
            result.unpersist()

        print("=== PharmStock Stage 7G / Kafka CDC Catch-up ===")
        print(f"Offset-range records: {expected_records:,}")
        print(f"Validated rows:       {total_rows:,}")
        print(f"Invalid rows:         {invalid_rows:,}")
        print("STAGE_7G_CDC_CATCHUP_STATUS=PASS")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
