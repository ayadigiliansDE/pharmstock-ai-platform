"""Stage 7G large-scale PostgreSQL -> Spark rebuild contracts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from pharmstock.cdc import CDC_TOPICS
from pharmstock.onprem import POSTGRES_DATABASE

SPARK_IMAGE: Final[str] = "apache/spark:4.2.0-python3"
SPARK_VERSION: Final[str] = "4.2.0"
SPARK_KAFKA_PACKAGE: Final[str] = "org.apache.spark:spark-sql-kafka-0-10_2.13:4.2.0"
POSTGRES_JDBC_PACKAGE: Final[str] = "org.postgresql:postgresql:42.7.13"
POSTGRES_JDBC_DRIVER: Final[str] = "org.postgresql.Driver"
POSTGRES_JDBC_URL: Final[str] = f"jdbc:postgresql://postgres:5432/{POSTGRES_DATABASE}"
POSTGRES_REBUILD_USER: Final[str] = "pharmstock_app"
BIGQUERY_REBUILD_DATASET: Final[str] = "pharmstock_ops_rebuild"
CDC_CHANGE_LOG_TABLE: Final[str] = "cdc_change_log"
HASH_PARTITION_UPPER_BOUND: Final[int] = 2_147_483_647


@dataclass(frozen=True, slots=True)
class SnapshotTableSpec:
    """One PostgreSQL table included in the controlled Stage 7G rebuild."""

    source_table: str
    primary_key: tuple[str, ...]
    jdbc_partitions: int
    category: str
    cdc_managed: bool

    @property
    def schema_name(self) -> str:
        return self.source_table.split(".", 1)[0]

    @property
    def table_name(self) -> str:
        return self.source_table.split(".", 1)[1]

    @property
    def artifact_path(self) -> str:
        return f"history/{self.schema_name}/{self.table_name}"

    @property
    def bigquery_table(self) -> str:
        return f"{self.schema_name}__{self.table_name}"


SNAPSHOT_TABLES: Final[tuple[SnapshotTableSpec, ...]] = (
    # Authoritative/public + calibrated master/commercial state.
    SnapshotTableSpec("master.product", ("product_id",), 2, "master", False),
    SnapshotTableSpec(
        "master.product_price_history", ("price_observation_id",), 2, "master", False
    ),
    SnapshotTableSpec(
        "master.pharmacy_organization", ("organization_id",), 1, "master", False
    ),
    SnapshotTableSpec("master.pharmacy_branch", ("branch_id",), 2, "master", False),
    SnapshotTableSpec(
        "commercial.product_unit_economics", ("product_id",), 2, "commercial", False
    ),
    SnapshotTableSpec(
        "commercial.branch_commercial_policy", ("branch_id",), 2, "commercial", False
    ),
    # POS/customer context used by the production-like historical model.
    SnapshotTableSpec("pos.terminal", ("terminal_id",), 2, "reference", False),
    SnapshotTableSpec("customer.household", ("household_id",), 4, "customer", False),
    SnapshotTableSpec(
        "customer.customer_profile", ("customer_id",), 4, "customer", False
    ),
    SnapshotTableSpec(
        "customer.loyalty_account", ("loyalty_account_id",), 4, "customer", False
    ),
    SnapshotTableSpec("customer.patient_profile", ("patient_id",), 4, "customer", False),
    SnapshotTableSpec(
        "pos.prescription_context", ("prescription_context_id",), 6, "historical", False
    ),
    SnapshotTableSpec("pos.demand_attempt", ("demand_attempt_id",), 8, "operational", True),
    # Stage 7F CDC-managed operational tables. These are snapshotted once, then CDC takes over.
    SnapshotTableSpec("pos.sale_header", ("sale_id",), 8, "operational", True),
    SnapshotTableSpec("pos.sale_line", ("sale_line_id",), 12, "operational", True),
    SnapshotTableSpec("pos.payment", ("payment_id",), 8, "operational", True),
    SnapshotTableSpec("pos.return_header", ("return_id",), 2, "operational", True),
    SnapshotTableSpec("pos.return_line", ("return_line_id",), 2, "operational", True),
    SnapshotTableSpec("inventory.stock_batch", ("batch_id",), 12, "operational", True),
    SnapshotTableSpec(
        "inventory.inventory_position",
        ("branch_id", "product_id"),
        12,
        "operational",
        True,
    ),
    SnapshotTableSpec(
        "inventory.stock_movement", ("movement_id",), 12, "operational", True
    ),
    SnapshotTableSpec("procurement.supplier", ("supplier_id",), 1, "operational", True),
    SnapshotTableSpec(
        "procurement.purchase_order", ("purchase_order_id",), 2, "operational", True
    ),
    SnapshotTableSpec(
        "procurement.purchase_order_line",
        ("purchase_order_line_id",),
        12,
        "operational",
        True,
    ),
    SnapshotTableSpec(
        "procurement.goods_receipt", ("receipt_id",), 2, "operational", True
    ),
    SnapshotTableSpec(
        "procurement.goods_receipt_line", ("receipt_line_id",), 12, "operational", True
    ),
)

SNAPSHOT_TABLE_BY_NAME: Final[dict[str, SnapshotTableSpec]] = {
    spec.source_table: spec for spec in SNAPSHOT_TABLES
}
CDC_SOURCE_TABLES: Final[tuple[str, ...]] = tuple(item.table for item in CDC_TOPICS)

CORE_ACCEPTANCE_MINIMUMS: Final[dict[str, int]] = {
    "master.pharmacy_branch": 5_000,
    "pos.sale_header": 1_200_000,
    "pos.sale_line": 2_000_000,
    "pos.payment": 1_200_000,
    "pos.demand_attempt": 2_000_000,
    "customer.customer_profile": 250_000,
    "customer.patient_profile": 300_000,
    "inventory.stock_movement": 2_000_000,
}


def _validate_offsets_shape(offsets: dict[str, dict[str, int]]) -> None:
    expected_topics = {item.topic for item in CDC_TOPICS}
    if set(offsets) != expected_topics:
        missing = sorted(expected_topics - set(offsets))
        extra = sorted(set(offsets) - expected_topics)
        raise ValueError(f"CDC offset topic mismatch missing={missing} extra={extra}")
    for topic, partitions in offsets.items():
        if not partitions:
            raise ValueError(f"CDC topic has no partitions: {topic}")
        for partition, offset in partitions.items():
            if not str(partition).isdigit() or int(offset) < 0:
                raise ValueError(f"invalid CDC offset {topic}:{partition}={offset}")


def validate_offset_range(
    start: dict[str, dict[str, int]], end: dict[str, dict[str, int]]
) -> int:
    """Validate a deterministic Kafka range and return its expected record count."""

    _validate_offsets_shape(start)
    _validate_offsets_shape(end)
    total = 0
    for topic, partitions in start.items():
        if set(partitions) != set(end[topic]):
            raise ValueError(f"partition mismatch for {topic}")
        for partition, start_offset in partitions.items():
            end_offset = int(end[topic][partition])
            if end_offset < int(start_offset):
                raise ValueError(
                    f"CDC offsets moved backwards {topic}:{partition} "
                    f"start={start_offset} end={end_offset}"
                )
            total += end_offset - int(start_offset)
    return total


def spark_offsets_json(offsets: dict[str, dict[str, int]]) -> str:
    """Return Spark Kafka starting/ending offsets JSON with stable ordering."""

    _validate_offsets_shape(offsets)
    normalized = {
        topic: {str(partition): int(value) for partition, value in sorted(parts.items())}
        for topic, parts in sorted(offsets.items())
    }
    return json.dumps(normalized, separators=(",", ":"), sort_keys=True)


def rebuild_contract() -> dict[str, object]:
    """Serializable Stage 7G architectural boundary."""

    return {
        "stage": "7G",
        "flow": (
            "KAFKA_CUTOVER_OFFSETS -> POSTGRESQL_JDBC_SNAPSHOT -> "
            "KAFKA_CDC_CATCHUP -> BIGQUERY_READY_PARQUET"
        ),
        "spark": {
            "image": SPARK_IMAGE,
            "version": SPARK_VERSION,
            "kafka_package": SPARK_KAFKA_PACKAGE,
            "postgres_jdbc_package": POSTGRES_JDBC_PACKAGE,
            "postgres_jdbc_driver": POSTGRES_JDBC_DRIVER,
        },
        "postgres": {
            "database": POSTGRES_DATABASE,
            "jdbc_url": POSTGRES_JDBC_URL,
            "read_user": POSTGRES_REBUILD_USER,
        },
        "snapshot_tables": [asdict(spec) for spec in SNAPSHOT_TABLES],
        "cdc_topics": [asdict(item) for item in CDC_TOPICS],
        "cutover": {
            "start_offsets_captured_before_snapshot": True,
            "end_offsets_captured_after_snapshot": True,
            "catchup_range": "[start_offset,end_offset)",
            "historical_rows_replayed_via_kafka": False,
            "cdc_resume_offsets": "end_offsets",
        },
        "bigquery": {
            "dataset": BIGQUERY_REBUILD_DATASET,
            "snapshot_table_naming": "<schema>__<table>",
            "cdc_change_log_table": CDC_CHANGE_LOG_TABLE,
            "cloud_mutation_in_checkpoint": False,
        },
        "privacy": {
            "customer_records": "SYNTHETIC_CALIBRATED_PRIVACY_SAFE",
            "direct_customer_pii_expected": False,
        },
    }


def write_rebuild_contract(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rebuild_contract(), ensure_ascii=False, indent=2), encoding="utf-8")
