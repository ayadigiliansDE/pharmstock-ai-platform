"""Stage 4A Spark Structured Streaming Kafka -> local Bronze foundation.

This job runs inside the pinned Apache Spark Docker image. It intentionally validates
only the stable domain-event envelope, preserves the raw payload, and writes one
idempotent directory per Spark micro-batch. Event-specific parsing belongs in Silver.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

from pharmstock.analytics.bronze import BRONZE_EVENT_TOPICS, BRONZE_TOPICS

SPARK_VERSION = "4.2.0"
KAFKA_CONNECTOR = "org.apache.spark:spark-sql-kafka-0-10_2.13:4.2.0"
UUID_REGEX = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
TZ_SUFFIX_REGEX = r"(Z|[+-][0-9]{2}:[0-9]{2})$"

ENVELOPE_SCHEMA = StructType(
    [
        StructField("event_id", StringType()),
        StructField("event_type", StringType()),
        StructField("schema_version", StringType()),
        StructField("aggregate_type", StringType()),
        StructField("aggregate_id", StringType()),
        StructField("occurred_at", StringType()),
        StructField("recorded_at", StringType()),
        StructField("correlation_id", StringType()),
        StructField("causation_id", StringType()),
    ]
)


def _setting(name: str, default: str) -> str:
    value = os.getenv(name, default).strip()
    if not value:
        raise ValueError(f"{name} cannot be empty")
    return value


def _expected_topic_expression() -> Any:
    expression = F.lit(None).cast("string")
    for event_type, topic in reversed(tuple(BRONZE_EVENT_TOPICS.items())):
        expression = F.when(F.col("event.event_type") == event_type, F.lit(topic)).otherwise(
            expression
        )
    return expression


def _validated_stream(source: DataFrame) -> DataFrame:
    raw_json = F.col("value").cast("string")
    expected_topic = _expected_topic_expression()
    occurred_ts = F.try_to_timestamp(F.col("event.occurred_at"))
    recorded_ts = F.try_to_timestamp(F.col("event.recorded_at"))
    payload_json = F.get_json_object(F.col("raw_json"), "$.payload")

    framed = (
        source.select(
            F.col("topic"),
            F.col("partition"),
            F.col("offset"),
            F.col("timestamp").alias("kafka_timestamp"),
            F.col("timestampType").alias("kafka_timestamp_type"),
            F.col("key").cast("string").alias("kafka_key"),
            F.col("headers"),
            raw_json.alias("raw_json"),
        )
        .withColumn("event", F.from_json(F.col("raw_json"), ENVELOPE_SCHEMA))
        .withColumn("payload_json", payload_json)
        .withColumn("expected_topic", expected_topic)
        .withColumn("occurred_ts", occurred_ts)
        .withColumn("recorded_ts", recorded_ts)
    )

    error = (
        F.when(F.col("event").isNull(), F.lit("malformed_or_non_object_json"))
        .when(
            F.col("event.event_id").isNull() | ~F.col("event.event_id").rlike(UUID_REGEX),
            F.lit("invalid_event_id"),
        )
        .when(
            F.col("event.event_type").isNull()
            | ~F.col("event.event_type").isin(*tuple(BRONZE_EVENT_TOPICS)),
            F.lit("unknown_event_type"),
        )
        .when(F.col("expected_topic") != F.col("topic"), F.lit("topic_event_type_mismatch"))
        .when(
            F.col("event.schema_version").isNull() | (F.col("event.schema_version") != "1.0"),
            F.lit("unsupported_schema_version"),
        )
        .when(
            F.col("event.aggregate_type").isNull()
            | (F.length(F.trim(F.col("event.aggregate_type"))) == 0),
            F.lit("invalid_aggregate_type"),
        )
        .when(
            F.col("event.aggregate_id").isNull()
            | ~F.col("event.aggregate_id").rlike(UUID_REGEX),
            F.lit("invalid_aggregate_id"),
        )
        .when(
            F.col("event.correlation_id").isNull()
            | ~F.col("event.correlation_id").rlike(UUID_REGEX),
            F.lit("invalid_correlation_id"),
        )
        .when(
            F.col("event.causation_id").isNotNull()
            & ~F.col("event.causation_id").rlike(UUID_REGEX),
            F.lit("invalid_causation_id"),
        )
        .when(
            F.col("kafka_key").isNull() | (F.col("kafka_key") != F.col("event.aggregate_id")),
            F.lit("kafka_key_mismatch"),
        )
        .when(
            F.col("occurred_ts").isNull()
            | ~F.col("event.occurred_at").rlike(TZ_SUFFIX_REGEX),
            F.lit("invalid_occurred_at"),
        )
        .when(
            F.col("recorded_ts").isNull()
            | ~F.col("event.recorded_at").rlike(TZ_SUFFIX_REGEX),
            F.lit("invalid_recorded_at"),
        )
        .when(
            F.col("payload_json").isNull() | ~F.col("payload_json").rlike(r"^\s*\{"),
            F.lit("payload_not_object"),
        )
        .otherwise(F.lit(None).cast("string"))
    )

    return (
        framed.withColumn("validation_error", error)
        .withColumn("event_date", F.to_date(F.col("occurred_ts")))
        .withColumn("ingested_at", F.current_timestamp())
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _parquet_exists(path: Path) -> bool:
    return path.exists() and any(path.rglob("*.parquet"))


def _read_parquet(spark: SparkSession, path: Path) -> DataFrame | None:
    if not _parquet_exists(path):
        return None
    return spark.read.option("recursiveFileLookup", "true").parquet(str(path))


def main() -> None:
    bootstrap_servers = _setting("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    output_root = Path(_setting("SPARK_STAGE4A_OUTPUT", "/opt/pharmstock/artifacts/stage4a"))
    checkpoint_dir = Path(
        _setting("SPARK_STAGE4A_CHECKPOINT", str(output_root / "spark_checkpoint"))
    )
    starting_offsets = _setting("SPARK_STAGE4A_STARTING_OFFSETS", "earliest")
    max_offsets = int(_setting("SPARK_STAGE4A_MAX_OFFSETS_PER_TRIGGER", "2000"))
    if max_offsets <= 0:
        raise ValueError("SPARK_STAGE4A_MAX_OFFSETS_PER_TRIGGER must be positive")

    bronze_dir = output_root / "bronze"
    quarantine_dir = output_root / "quarantine"
    metrics_dir = output_root / "batch_metrics"
    output_root.mkdir(parents=True, exist_ok=True)
    metrics_dir.mkdir(parents=True, exist_ok=True)

    spark = (
        SparkSession.builder.appName("pharmstock-stage4a-bronze")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "4")
        .config("spark.sql.adaptive.enabled", "true")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    source = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", bootstrap_servers)
        .option("subscribe", ",".join(BRONZE_TOPICS))
        .option("startingOffsets", starting_offsets)
        .option("failOnDataLoss", "false")
        .option("includeHeaders", "true")
        .option("maxOffsetsPerTrigger", str(max_offsets))
        .load()
    )
    validated = _validated_stream(source)
    run_batches: list[dict[str, int]] = []

    def process_batch(batch: DataFrame, batch_id: int) -> None:
        batch = batch.persist()
        try:
            input_rows = batch.count()
            valid = batch.filter(F.col("validation_error").isNull()).drop("event", "expected_topic")
            invalid = batch.filter(F.col("validation_error").isNotNull()).drop(
                "event", "expected_topic"
            )
            valid_rows = valid.count()
            invalid_rows = invalid.count()
            if input_rows != valid_rows + invalid_rows:
                raise RuntimeError("Stage 4A batch accounting mismatch")

            batch_name = f"batch_id={batch_id:020d}"
            if valid_rows:
                (
                    valid.withColumn("spark_batch_id", F.lit(batch_id))
                    .write.mode("overwrite")
                    .parquet(str(bronze_dir / batch_name))
                )
            if invalid_rows:
                (
                    invalid.withColumn("spark_batch_id", F.lit(batch_id))
                    .write.mode("overwrite")
                    .parquet(str(quarantine_dir / batch_name))
                )

            metric = {
                "batch_id": int(batch_id),
                "input_rows": int(input_rows),
                "bronze_rows": int(valid_rows),
                "quarantine_rows": int(invalid_rows),
            }
            _write_json(metrics_dir / f"batch-{batch_id:020d}.json", metric)
            run_batches.append(metric)
            print(
                "Stage4A batch "
                f"{batch_id}: input={input_rows:,} bronze={valid_rows:,} "
                f"quarantine={invalid_rows:,}"
            )
        finally:
            batch.unpersist()

    query = (
        validated.writeStream.foreachBatch(process_batch)
        .option("checkpointLocation", str(checkpoint_dir))
        .queryName("pharmstock-stage4a-bronze")
        .trigger(availableNow=True)
        .start()
    )
    query.awaitTermination()

    bronze_frame = _read_parquet(spark, bronze_dir)
    quarantine_frame = _read_parquet(spark, quarantine_dir)
    cumulative_bronze = 0 if bronze_frame is None else bronze_frame.count()
    cumulative_quarantine = 0 if quarantine_frame is None else quarantine_frame.count()
    position_frames = [
        frame.select("topic", "partition", "offset")
        for frame in (bronze_frame, quarantine_frame)
        if frame is not None
    ]
    if position_frames:
        positions = position_frames[0]
        for frame in position_frames[1:]:
            positions = positions.unionByName(frame)
        total_rows = positions.count()
        distinct_source_positions = positions.dropDuplicates().count()
    else:
        total_rows = 0
        distinct_source_positions = 0
    duplicate_source_positions = total_rows - distinct_source_positions

    summary = {
        "stage": "4A",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "spark_version": spark.version,
        "expected_spark_version": SPARK_VERSION,
        "kafka_connector": KAFKA_CONNECTOR,
        "bootstrap_servers": bootstrap_servers,
        "topics": list(BRONZE_TOPICS),
        "starting_offsets_for_new_checkpoint": starting_offsets,
        "max_offsets_per_trigger": max_offsets,
        "run_batches": run_batches,
        "new_batches": len(run_batches),
        "new_input_rows": sum(item["input_rows"] for item in run_batches),
        "new_bronze_rows": sum(item["bronze_rows"] for item in run_batches),
        "new_quarantine_rows": sum(item["quarantine_rows"] for item in run_batches),
        "cumulative_bronze_rows": cumulative_bronze,
        "cumulative_quarantine_rows": cumulative_quarantine,
        "cumulative_source_positions": total_rows,
        "duplicate_kafka_source_positions": duplicate_source_positions,
        "source_identity": ["topic", "partition", "offset"],
        "sink_contract": "DETERMINISTIC_SPARK_BATCH_PATH_OVERWRITE_PLUS_CHECKPOINT",
        "bronze_contract": "COMMON_ENVELOPE_VALIDATION_RAW_PAYLOAD_PRESERVED",
    }
    _write_json(output_root / "run_summary.json", summary)
    if duplicate_source_positions:
        raise RuntimeError(
            f"duplicate Kafka source positions detected in Bronze/quarantine: "
            f"{duplicate_source_positions}"
        )
    (output_root / "_SPARK_SUCCESS").write_text("STAGE_4A_SPARK_PASS\n", encoding="utf-8")

    print("\n=== PharmStock Stage 4A Spark Bronze ===")
    print(f"Spark version:            {spark.version}")
    print(f"New micro-batches:        {len(run_batches):,}")
    print(f"New input rows:           {summary['new_input_rows']:,}")
    print(f"New Bronze rows:          {summary['new_bronze_rows']:,}")
    print(f"New quarantine rows:      {summary['new_quarantine_rows']:,}")
    print(f"Cumulative Bronze rows:   {cumulative_bronze:,}")
    print(f"Cumulative quarantine:    {cumulative_quarantine:,}")
    print("Duplicate Kafka positions:0")
    print("STAGE_4A_SPARK_STATUS=PASS")
    spark.stop()


if __name__ == "__main__":
    main()
