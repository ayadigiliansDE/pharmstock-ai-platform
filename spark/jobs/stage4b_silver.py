"""Stage 4B Spark Bronze -> Silver normalization and event-id deduplication.

The job is intentionally a deterministic batch/full-refresh transformation over the local
Stage 4A Bronze Parquet dataset. Bronze keeps every Kafka source position; Silver keeps one
canonical row per non-conflicting domain ``event_id`` and writes exact replay copies to an
audit dataset. Event-id reuse with different semantic content is rejected as a conflict.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql.types import (
    BooleanType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

from pharmstock.analytics.silver_contracts import SILVER_TABLE_BY_EVENT

SPARK_VERSION = "4.2.0"
UUID_REGEX = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

COMMON_SCHEMA = StructType(
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

SALE_SCHEMA = StructType(
    [
        StructField("demand_id", StringType()),
        StructField("basket_id", StringType()),
        StructField("branch_id", StringType()),
        StructField("product_id", StringType()),
        StructField("channel", StringType()),
        StructField("requested_quantity", IntegerType()),
        StructField("fulfilled_quantity", IntegerType()),
        StructField("lost_quantity", IntegerType()),
        StructField("fulfillment_status", StringType()),
        StructField("pricing_status", StringType()),
    ]
)

INVENTORY_SCHEMA = StructType(
    [
        StructField("movement_id", StringType()),
        StructField("branch_id", StringType()),
        StructField("product_id", StringType()),
        StructField("movement_type", StringType()),
        StructField("quantity_delta", IntegerType()),
        StructField("on_hand_before", IntegerType()),
        StructField("on_hand_after", IntegerType()),
        StructField("inventory_version_after", IntegerType()),
        StructField("reference_id", StringType()),
    ]
)

REORDER_SCHEMA = StructType(
    [
        StructField("branch_id", StringType()),
        StructField("product_id", StringType()),
        StructField("available_quantity", IntegerType()),
        StructField("reorder_point", IntegerType()),
        StructField("target_stock_level", IntegerType()),
        StructField("recommended_reorder_quantity", IntegerType()),
        StructField("inventory_version", IntegerType()),
    ]
)

PURCHASE_ORDER_SCHEMA = StructType(
    [
        StructField("purchase_order_id", StringType()),
        StructField("procurement_cycle_id", StringType()),
        StructField("branch_id", StringType()),
        StructField("supplier_id", StringType()),
        StructField("expected_delivery_on", StringType()),
        StructField("line_count", IntegerType()),
        StructField("ordered_units", IntegerType()),
        StructField("monetary_values_generated", BooleanType()),
    ]
)

RECEIPT_SCHEMA = StructType(
    [
        StructField("receipt_id", StringType()),
        StructField("purchase_order_id", StringType()),
        StructField("branch_id", StringType()),
        StructField("supplier_id", StringType()),
        StructField("line_count", IntegerType()),
        StructField("received_units", IntegerType()),
    ]
)

RESTOCK_SCHEMA = StructType(
    [
        StructField("movement_id", StringType()),
        StructField("receipt_id", StringType()),
        StructField("purchase_order_id", StringType()),
        StructField("branch_id", StringType()),
        StructField("product_id", StringType()),
        StructField("quantity", IntegerType()),
        StructField("on_hand_before", IntegerType()),
        StructField("on_hand_after", IntegerType()),
        StructField("inventory_version_after", IntegerType()),
    ]
)

COMMON_OUTPUT_COLUMNS = [
    "event_id",
    "event_type",
    "schema_version",
    "aggregate_type",
    "aggregate_id",
    "occurred_at",
    "recorded_at",
    "correlation_id",
    "causation_id",
    "event_date",
    "kafka_topic",
    "kafka_partition",
    "kafka_offset",
    "kafka_timestamp",
    "kafka_key",
    "semantic_event_sha256",
    "silver_processed_at",
]


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


def _uuid(column: Any) -> Any:
    return column.isNotNull() & column.rlike(UUID_REGEX)


def _base_frame(bronze: DataFrame) -> DataFrame:
    event = F.from_json(F.col("raw_json"), COMMON_SCHEMA)
    semantic_material = F.concat_ws(
        "||",
        event["event_id"],
        event["event_type"],
        event["schema_version"],
        event["aggregate_type"],
        event["aggregate_id"],
        event["occurred_at"],
        F.coalesce(event["correlation_id"], F.lit("")),
        F.coalesce(event["causation_id"], F.lit("")),
        F.col("payload_json"),
    )
    return (
        bronze.withColumn("event", event)
        .withColumn("semantic_event_sha256", F.sha2(semantic_material, 256))
        .withColumnRenamed("topic", "kafka_topic")
        .withColumnRenamed("partition", "kafka_partition")
        .withColumnRenamed("offset", "kafka_offset")
    )


def _common_output_expressions() -> list[Any]:
    return [
        F.col("event.event_id").alias("event_id"),
        F.col("event.event_type").alias("event_type"),
        F.col("event.schema_version").alias("schema_version"),
        F.col("event.aggregate_type").alias("aggregate_type"),
        F.col("event.aggregate_id").alias("aggregate_id"),
        F.col("occurred_ts").alias("occurred_at"),
        F.col("recorded_ts").alias("recorded_at"),
        F.col("event.correlation_id").alias("correlation_id"),
        F.col("event.causation_id").alias("causation_id"),
        F.col("event_date"),
        F.col("kafka_topic"),
        F.col("kafka_partition"),
        F.col("kafka_offset"),
        F.col("kafka_timestamp"),
        F.col("kafka_key"),
        F.col("semantic_event_sha256"),
        F.current_timestamp().alias("silver_processed_at"),
    ]


def _deduplicate(base: DataFrame) -> tuple[DataFrame, DataFrame, DataFrame]:
    conflicts = (
        base.groupBy(F.col("event.event_id").alias("event_id"))
        .agg(F.countDistinct("semantic_event_sha256").alias("semantic_versions"))
        .filter(F.col("semantic_versions") > 1)
    )
    conflict_rows = base.join(
        conflicts.select(F.col("event_id").alias("conflict_event_id")),
        F.col("event.event_id") == F.col("conflict_event_id"),
        "inner",
    ).drop("conflict_event_id")

    non_conflict = base.join(
        conflicts.select(F.col("event_id").alias("conflict_event_id")),
        F.col("event.event_id") == F.col("conflict_event_id"),
        "left_anti",
    )
    ordering = Window.partitionBy("event.event_id").orderBy(
        F.col("kafka_timestamp").asc(),
        F.col("kafka_topic").asc(),
        F.col("kafka_partition").asc(),
        F.col("kafka_offset").asc(),
    )
    ranked = non_conflict.withColumn("event_occurrence_rank", F.row_number().over(ordering))
    canonical = ranked.filter(F.col("event_occurrence_rank") == 1).drop("event_occurrence_rank")
    duplicates = ranked.filter(F.col("event_occurrence_rank") > 1)
    return canonical, duplicates, conflict_rows


def _invalid_sale() -> Any:
    p = F.col("payload")
    return (
        ~_uuid(p["demand_id"])
        | ~_uuid(p["basket_id"])
        | ~_uuid(p["branch_id"])
        | ~_uuid(p["product_id"])
        | p["channel"].isNull()
        | (F.length(F.trim(p["channel"])) == 0)
        | p["requested_quantity"].isNull()
        | (p["requested_quantity"] <= 0)
        | p["fulfilled_quantity"].isNull()
        | (p["fulfilled_quantity"] <= 0)
        | p["lost_quantity"].isNull()
        | (p["lost_quantity"] < 0)
        | ((p["fulfilled_quantity"] + p["lost_quantity"]) != p["requested_quantity"])
        | p["fulfillment_status"].isNull()
        | ~p["fulfillment_status"].isin("fulfilled", "partial")
        | p["pricing_status"].isNull()
        | (p["pricing_status"] != "not_simulated")
    )


def _invalid_inventory() -> Any:
    p = F.col("payload")
    return (
        ~_uuid(p["movement_id"])
        | ~_uuid(p["branch_id"])
        | ~_uuid(p["product_id"])
        | ~_uuid(p["reference_id"])
        | p["movement_type"].isNull()
        | ~p["movement_type"].isin("sale", "restock")
        | p["quantity_delta"].isNull()
        | (p["quantity_delta"] == 0)
        | p["on_hand_before"].isNull()
        | (p["on_hand_before"] < 0)
        | p["on_hand_after"].isNull()
        | (p["on_hand_after"] < 0)
        | p["inventory_version_after"].isNull()
        | (p["inventory_version_after"] < 2)
        | ((p["on_hand_before"] + p["quantity_delta"]) != p["on_hand_after"])
        | ((p["movement_type"] == "sale") & (p["quantity_delta"] >= 0))
        | ((p["movement_type"] == "restock") & (p["quantity_delta"] <= 0))
    )


def _invalid_reorder() -> Any:
    p = F.col("payload")
    return (
        ~_uuid(p["branch_id"])
        | ~_uuid(p["product_id"])
        | p["available_quantity"].isNull()
        | (p["available_quantity"] < 0)
        | p["reorder_point"].isNull()
        | (p["reorder_point"] < 0)
        | p["target_stock_level"].isNull()
        | (p["target_stock_level"] <= 0)
        | p["recommended_reorder_quantity"].isNull()
        | (p["recommended_reorder_quantity"] <= 0)
        | p["inventory_version"].isNull()
        | (p["inventory_version"] < 1)
    )


def _invalid_purchase_order() -> Any:
    p = F.col("payload")
    expected_date = F.expr("try_cast(payload.expected_delivery_on AS DATE)")
    return (
        ~_uuid(p["purchase_order_id"])
        | ~_uuid(p["procurement_cycle_id"])
        | ~_uuid(p["branch_id"])
        | ~_uuid(p["supplier_id"])
        | expected_date.isNull()
        | p["line_count"].isNull()
        | (p["line_count"] <= 0)
        | p["ordered_units"].isNull()
        | (p["ordered_units"] <= 0)
        | p["monetary_values_generated"].isNull()
        | (p["monetary_values_generated"] != F.lit(False))
    )


def _invalid_receipt() -> Any:
    p = F.col("payload")
    return (
        ~_uuid(p["receipt_id"])
        | ~_uuid(p["purchase_order_id"])
        | ~_uuid(p["branch_id"])
        | ~_uuid(p["supplier_id"])
        | p["line_count"].isNull()
        | (p["line_count"] <= 0)
        | p["received_units"].isNull()
        | (p["received_units"] <= 0)
    )


def _invalid_restock() -> Any:
    p = F.col("payload")
    return (
        ~_uuid(p["movement_id"])
        | ~_uuid(p["receipt_id"])
        | ~_uuid(p["purchase_order_id"])
        | ~_uuid(p["branch_id"])
        | ~_uuid(p["product_id"])
        | p["quantity"].isNull()
        | (p["quantity"] <= 0)
        | p["on_hand_before"].isNull()
        | (p["on_hand_before"] < 0)
        | p["on_hand_after"].isNull()
        | (p["on_hand_after"] < 0)
        | p["inventory_version_after"].isNull()
        | (p["inventory_version_after"] < 2)
        | ((p["on_hand_before"] + p["quantity"]) != p["on_hand_after"])
    )


def _normalize_event(
    canonical: DataFrame,
    *,
    event_type: str,
    schema: StructType,
    invalid_condition: Any,
    payload_columns: list[Any],
) -> tuple[DataFrame, DataFrame]:
    framed = canonical.filter(F.col("event.event_type") == event_type).withColumn(
        "payload", F.from_json(F.col("payload_json"), schema)
    )
    invalid = F.col("payload").isNull() | invalid_condition
    valid_rows = framed.filter(~invalid)
    reject_rows = framed.filter(invalid).select(
        F.col("event.event_id").alias("event_id"),
        F.col("event.event_type").alias("event_type"),
        F.lit("payload_schema_or_business_rule_invalid").alias("rejection_reason"),
        F.col("kafka_topic"),
        F.col("kafka_partition"),
        F.col("kafka_offset"),
        F.col("semantic_event_sha256"),
        F.col("raw_json"),
    )
    normalized = valid_rows.select(
        *_common_output_expressions(),
        *payload_columns,
    )
    return normalized, reject_rows


def _event_outputs(canonical: DataFrame) -> dict[str, tuple[DataFrame, DataFrame]]:
    p = F.col("payload")
    return {
        "sales_units_fulfilled": _normalize_event(
            canonical,
            event_type="sale.units_fulfilled",
            schema=SALE_SCHEMA,
            invalid_condition=_invalid_sale(),
            payload_columns=[
                p["demand_id"].alias("demand_id"),
                p["basket_id"].alias("basket_id"),
                p["branch_id"].alias("branch_id"),
                p["product_id"].alias("product_id"),
                p["channel"].alias("channel"),
                p["requested_quantity"].alias("requested_quantity"),
                p["fulfilled_quantity"].alias("fulfilled_quantity"),
                p["lost_quantity"].alias("lost_quantity"),
                p["fulfillment_status"].alias("fulfillment_status"),
                p["pricing_status"].alias("pricing_status"),
            ],
        ),
        "inventory_quantity_changed": _normalize_event(
            canonical,
            event_type="inventory.quantity_changed",
            schema=INVENTORY_SCHEMA,
            invalid_condition=_invalid_inventory(),
            payload_columns=[
                p["movement_id"].alias("movement_id"),
                p["branch_id"].alias("branch_id"),
                p["product_id"].alias("product_id"),
                p["movement_type"].alias("movement_type"),
                p["quantity_delta"].alias("quantity_delta"),
                p["on_hand_before"].alias("on_hand_before"),
                p["on_hand_after"].alias("on_hand_after"),
                p["inventory_version_after"].alias("inventory_version_after"),
                p["reference_id"].alias("reference_id"),
            ],
        ),
        "inventory_reorder_required": _normalize_event(
            canonical,
            event_type="inventory.reorder_required",
            schema=REORDER_SCHEMA,
            invalid_condition=_invalid_reorder(),
            payload_columns=[
                p["branch_id"].alias("branch_id"),
                p["product_id"].alias("product_id"),
                p["available_quantity"].alias("available_quantity"),
                p["reorder_point"].alias("reorder_point"),
                p["target_stock_level"].alias("target_stock_level"),
                p["recommended_reorder_quantity"].alias("recommended_reorder_quantity"),
                p["inventory_version"].alias("inventory_version"),
            ],
        ),
        "purchase_order_created": _normalize_event(
            canonical,
            event_type="purchase_order.created",
            schema=PURCHASE_ORDER_SCHEMA,
            invalid_condition=_invalid_purchase_order(),
            payload_columns=[
                p["purchase_order_id"].alias("purchase_order_id"),
                p["procurement_cycle_id"].alias("procurement_cycle_id"),
                p["branch_id"].alias("branch_id"),
                p["supplier_id"].alias("supplier_id"),
                F.expr("try_cast(payload.expected_delivery_on AS DATE)").alias(
                    "expected_delivery_on"
                ),
                p["line_count"].alias("line_count"),
                p["ordered_units"].alias("ordered_units"),
                p["monetary_values_generated"].alias("monetary_values_generated"),
            ],
        ),
        "goods_receipt_received": _normalize_event(
            canonical,
            event_type="goods_receipt.received",
            schema=RECEIPT_SCHEMA,
            invalid_condition=_invalid_receipt(),
            payload_columns=[
                p["receipt_id"].alias("receipt_id"),
                p["purchase_order_id"].alias("purchase_order_id"),
                p["branch_id"].alias("branch_id"),
                p["supplier_id"].alias("supplier_id"),
                p["line_count"].alias("line_count"),
                p["received_units"].alias("received_units"),
            ],
        ),
        "restock_applied": _normalize_event(
            canonical,
            event_type="restock.applied",
            schema=RESTOCK_SCHEMA,
            invalid_condition=_invalid_restock(),
            payload_columns=[
                p["movement_id"].alias("movement_id"),
                p["receipt_id"].alias("receipt_id"),
                p["purchase_order_id"].alias("purchase_order_id"),
                p["branch_id"].alias("branch_id"),
                p["product_id"].alias("product_id"),
                p["quantity"].alias("quantity"),
                p["on_hand_before"].alias("on_hand_before"),
                p["on_hand_after"].alias("on_hand_after"),
                p["inventory_version_after"].alias("inventory_version_after"),
            ],
        ),
    }


def _write_frame(frame: DataFrame, path: Path, *, partitioned: bool = False) -> None:
    if frame.limit(1).count() == 0:
        return
    writer = frame.write.mode("overwrite")
    if partitioned:
        writer = writer.partitionBy("event_date")
    writer.parquet(str(path))


def main() -> None:
    bronze_dir = Path(
        _setting("SPARK_STAGE4B_BRONZE", "/opt/pharmstock/artifacts/stage4a/bronze")
    )
    output_root = Path(_setting("SPARK_STAGE4B_OUTPUT", "/opt/pharmstock/artifacts/stage4b"))
    silver_root = output_root / "silver"
    audit_root = output_root / "audit"
    if not bronze_dir.exists():
        raise FileNotFoundError(f"Stage 4A Bronze input is missing: {bronze_dir}")

    output_root.mkdir(parents=True, exist_ok=True)
    for refresh_path in (silver_root, audit_root):
        if refresh_path.exists():
            shutil.rmtree(refresh_path)
    (output_root / "run_summary.json").unlink(missing_ok=True)
    (output_root / "_SPARK_SUCCESS").unlink(missing_ok=True)
    silver_root.mkdir(parents=True, exist_ok=True)
    audit_root.mkdir(parents=True, exist_ok=True)

    spark = (
        SparkSession.builder.appName("pharmstock-stage4b-silver")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "4")
        .config("spark.sql.adaptive.enabled", "true")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    bronze = spark.read.option("recursiveFileLookup", "true").parquet(str(bronze_dir)).persist()
    try:
        bronze_rows = bronze.count()
        base = _base_frame(bronze).persist()
        try:
            canonical, duplicates, conflicts = _deduplicate(base)
            canonical = canonical.persist()
            duplicates = duplicates.persist()
            conflicts = conflicts.persist()
            try:
                outputs = _event_outputs(canonical)
                table_counts: dict[str, int] = {}
                reject_frames: list[DataFrame] = []
                event_index_frames: list[DataFrame] = []
                silver_rows = 0
                for table_name, (valid, rejects) in outputs.items():
                    count = valid.count()
                    table_counts[table_name] = count
                    silver_rows += count
                    if count:
                        _write_frame(valid, silver_root / table_name, partitioned=True)
                        event_index_frames.append(
                            valid.select(*COMMON_OUTPUT_COLUMNS).withColumn(
                                "silver_table", F.lit(table_name)
                            )
                        )
                    if rejects.limit(1).count():
                        reject_frames.append(rejects)

                if event_index_frames:
                    event_index = event_index_frames[0]
                    for frame in event_index_frames[1:]:
                        event_index = event_index.unionByName(frame)
                    _write_frame(event_index, silver_root / "event_index", partitioned=True)
                    unique_silver_events = event_index.select("event_id").distinct().count()
                else:
                    unique_silver_events = 0

                if reject_frames:
                    rejects = reject_frames[0]
                    for frame in reject_frames[1:]:
                        rejects = rejects.unionByName(frame)
                    reject_rows = rejects.count()
                    _write_frame(rejects, audit_root / "payload_rejects")
                else:
                    reject_rows = 0

                duplicate_rows = duplicates.count()
                conflict_rows = conflicts.count()
                conflict_event_ids = conflicts.select("event.event_id").distinct().count()
                if duplicate_rows:
                    duplicate_audit = duplicates.select(
                        F.col("event.event_id").alias("event_id"),
                        F.col("event.event_type").alias("event_type"),
                        F.col("kafka_topic"),
                        F.col("kafka_partition"),
                        F.col("kafka_offset"),
                        F.col("kafka_timestamp"),
                        F.col("semantic_event_sha256"),
                        F.col("event_occurrence_rank"),
                    )
                    _write_frame(duplicate_audit, audit_root / "exact_duplicates")
                if conflict_rows:
                    conflict_audit = conflicts.select(
                        F.col("event.event_id").alias("event_id"),
                        F.col("event.event_type").alias("event_type"),
                        F.col("kafka_topic"),
                        F.col("kafka_partition"),
                        F.col("kafka_offset"),
                        F.col("semantic_event_sha256"),
                        F.col("raw_json"),
                    )
                    _write_frame(conflict_audit, audit_root / "event_id_conflicts")

                accounted_rows = silver_rows + reject_rows + duplicate_rows + conflict_rows
                if accounted_rows != bronze_rows:
                    raise RuntimeError(
                        "Stage 4B accounting mismatch: "
                        f"bronze={bronze_rows} accounted={accounted_rows}"
                    )
                if unique_silver_events != silver_rows:
                    raise RuntimeError("Stage 4B Silver contains duplicate event_id values")

                summary = {
                    "stage": "4B",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "spark_version": spark.version,
                    "expected_spark_version": SPARK_VERSION,
                    "bronze_rows": bronze_rows,
                    "silver_rows": silver_rows,
                    "unique_silver_event_ids": unique_silver_events,
                    "exact_duplicate_rows": duplicate_rows,
                    "payload_reject_rows": reject_rows,
                    "conflict_rows": conflict_rows,
                    "conflict_event_ids": conflict_event_ids,
                    "accounted_rows": accounted_rows,
                    "table_counts": table_counts,
                    "deduplication_key": "event_id",
                    "semantic_hash_excludes": ["recorded_at"],
                    "canonical_selection": "kafka_timestamp_topic_partition_offset_ascending",
                    "source_lineage": ["kafka_topic", "kafka_partition", "kafka_offset"],
                    "silver_mode": "DETERMINISTIC_FULL_REFRESH_FROM_BRONZE_V1",
                    "conflict_policy": "REJECT_ALL_ROWS_FOR_EVENT_ID_WITH_MULTIPLE_SEMANTIC_HASHES",
                }
                _write_json(output_root / "run_summary.json", summary)
                (output_root / "_SPARK_SUCCESS").write_text(
                    "STAGE_4B_SPARK_PASS\n", encoding="utf-8"
                )

                print("\n=== PharmStock Stage 4B Spark Silver ===")
                print(f"Spark version:              {spark.version}")
                print(f"Bronze rows:                {bronze_rows:,}")
                print(f"Silver rows:                {silver_rows:,}")
                print(f"Exact duplicates removed:   {duplicate_rows:,}")
                print(f"Payload rejects:             {reject_rows:,}")
                print(f"Event-ID conflict rows:      {conflict_rows:,}")
                print(f"Unique Silver event IDs:     {unique_silver_events:,}")
                print("Silver tables:")
                for table_name in SILVER_TABLE_BY_EVENT.values():
                    print(f"  {table_name:<34} {table_counts.get(table_name, 0):>8,}")
                print("STAGE_4B_SPARK_STATUS=PASS")
            finally:
                canonical.unpersist()
                duplicates.unpersist()
                conflicts.unpersist()
        finally:
            base.unpersist()
    finally:
        bronze.unpersist()
        spark.stop()


if __name__ == "__main__":
    main()
