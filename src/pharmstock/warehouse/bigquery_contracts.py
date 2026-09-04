"""Dependency-light BigQuery warehouse contracts for Stage 5A.

The module deliberately uses only the Python standard library so Spark's pinned Python
runtime can import the contracts without pulling the application/domain dependency graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class BigQueryField:
    name: str
    field_type: str
    mode: str = "NULLABLE"
    description: str = ""

    def to_api_repr(self) -> dict[str, str]:
        return {
            "name": self.name,
            "type": self.field_type,
            "mode": self.mode,
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class BigQueryTableContract:
    table_name: str
    source_silver_table: str
    fields: tuple[BigQueryField, ...]
    partition_field: str
    clustering_fields: tuple[str, ...]
    description: str

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields)

    def to_catalog_entry(self) -> dict[str, object]:
        return {
            "table_name": self.table_name,
            "source_silver_table": self.source_silver_table,
            "partition_field": self.partition_field,
            "clustering_fields": list(self.clustering_fields),
            "description": self.description,
            "schema": [field.to_api_repr() for field in self.fields],
        }


COMMON_FIELDS: Final[tuple[BigQueryField, ...]] = (
    BigQueryField("event_id", "STRING", "REQUIRED", "Stable domain event UUID."),
    BigQueryField("event_type", "STRING", "REQUIRED", "Versioned operational event type."),
    BigQueryField("schema_version", "STRING", "REQUIRED", "Domain event schema version."),
    BigQueryField("aggregate_type", "STRING", "REQUIRED", "Domain aggregate type."),
    BigQueryField("aggregate_id", "STRING", "REQUIRED", "Domain aggregate UUID."),
    BigQueryField("occurred_at", "TIMESTAMP", "REQUIRED", "Business occurrence timestamp, UTC."),
    BigQueryField("recorded_at", "TIMESTAMP", "REQUIRED", "Event recording timestamp, UTC."),
    BigQueryField("correlation_id", "STRING", "NULLABLE", "Cross-event correlation identifier."),
    BigQueryField("causation_id", "STRING", "NULLABLE", "Identifier of the causal parent event."),
    BigQueryField("event_date", "DATE", "REQUIRED", "UTC event date used for partitioning."),
    BigQueryField("kafka_topic", "STRING", "REQUIRED", "Source Kafka topic."),
    BigQueryField("kafka_partition", "INTEGER", "REQUIRED", "Source Kafka partition."),
    BigQueryField("kafka_offset", "INTEGER", "REQUIRED", "Source Kafka offset."),
    BigQueryField("kafka_timestamp", "TIMESTAMP", "REQUIRED", "Kafka broker message timestamp."),
    BigQueryField("kafka_key", "STRING", "NULLABLE", "Kafka message key decoded as UTF-8."),
    BigQueryField(
        "semantic_event_sha256",
        "STRING",
        "REQUIRED",
        "SHA-256 of event semantics excluding recorded_at.",
    ),
    BigQueryField("silver_processed_at", "TIMESTAMP", "REQUIRED", "Silver processing timestamp."),
)


TABLE_CONTRACTS: Final[dict[str, BigQueryTableContract]] = {
    "event_index": BigQueryTableContract(
        table_name="event_index",
        source_silver_table="event_index",
        fields=COMMON_FIELDS
        + (BigQueryField("silver_table", "STRING", "REQUIRED", "Owning normalized Silver table."),),
        partition_field="event_date",
        clustering_fields=("event_type", "aggregate_type", "aggregate_id"),
        description="One unique row per accepted operational event with Kafka lineage.",
    ),
    "sales_units_fulfilled": BigQueryTableContract(
        table_name="sales_units_fulfilled",
        source_silver_table="sales_units_fulfilled",
        fields=COMMON_FIELDS
        + (
            BigQueryField("demand_id", "STRING", "REQUIRED", "Synthetic demand-line UUID."),
            BigQueryField("basket_id", "STRING", "REQUIRED", "Synthetic basket UUID."),
            BigQueryField("branch_id", "STRING", "REQUIRED", "Pharmacy branch UUID."),
            BigQueryField("product_id", "STRING", "REQUIRED", "Canonical product UUID."),
            BigQueryField("channel", "STRING", "REQUIRED", "Fulfillment channel."),
            BigQueryField("requested_quantity", "INTEGER", "REQUIRED", "Requested units."),
            BigQueryField("fulfilled_quantity", "INTEGER", "REQUIRED", "Fulfilled units."),
            BigQueryField("lost_quantity", "INTEGER", "REQUIRED", "Unfulfilled units."),
            BigQueryField("fulfillment_status", "STRING", "REQUIRED", "fulfilled or partial."),
            BigQueryField("pricing_status", "STRING", "REQUIRED", "Pricing provenance/status."),
        ),
        partition_field="event_date",
        clustering_fields=("branch_id", "product_id", "channel"),
        description="Unit-level demand fulfillment facts; no monetary values are generated.",
    ),
    "inventory_quantity_changed": BigQueryTableContract(
        table_name="inventory_quantity_changed",
        source_silver_table="inventory_quantity_changed",
        fields=COMMON_FIELDS
        + (
            BigQueryField("movement_id", "STRING", "REQUIRED", "Stock movement UUID."),
            BigQueryField("branch_id", "STRING", "REQUIRED", "Pharmacy branch UUID."),
            BigQueryField("product_id", "STRING", "REQUIRED", "Canonical product UUID."),
            BigQueryField("movement_type", "STRING", "REQUIRED", "sale or restock."),
            BigQueryField("quantity_delta", "INTEGER", "REQUIRED", "Signed stock movement units."),
            BigQueryField(
                "on_hand_before",
                "INTEGER",
                "REQUIRED",
                "On-hand units before movement.",
            ),
            BigQueryField("on_hand_after", "INTEGER", "REQUIRED", "On-hand units after movement."),
            BigQueryField(
                "inventory_version_after",
                "INTEGER",
                "REQUIRED",
                "Inventory version after movement.",
            ),
            BigQueryField(
                "reference_id",
                "STRING",
                "REQUIRED",
                "Source sale/receipt reference UUID.",
            ),
        ),
        partition_field="event_date",
        clustering_fields=("branch_id", "product_id", "movement_type"),
        description="Inventory movement facts with before/after quantities and Kafka lineage.",
    ),
    "inventory_reorder_required": BigQueryTableContract(
        table_name="inventory_reorder_required",
        source_silver_table="inventory_reorder_required",
        fields=COMMON_FIELDS
        + (
            BigQueryField("branch_id", "STRING", "REQUIRED", "Pharmacy branch UUID."),
            BigQueryField("product_id", "STRING", "REQUIRED", "Canonical product UUID."),
            BigQueryField(
                "available_quantity",
                "INTEGER",
                "REQUIRED",
                "Available units at trigger.",
            ),
            BigQueryField("reorder_point", "INTEGER", "REQUIRED", "Configured reorder point."),
            BigQueryField("target_stock_level", "INTEGER", "REQUIRED", "Configured target level."),
            BigQueryField(
                "recommended_reorder_quantity",
                "INTEGER",
                "REQUIRED",
                "Recommended units to replenish.",
            ),
            BigQueryField(
                "inventory_version",
                "INTEGER",
                "REQUIRED",
                "Inventory version at trigger.",
            ),
        ),
        partition_field="event_date",
        clustering_fields=("branch_id", "product_id"),
        description="Reorder-threshold crossing facts for inventory planning.",
    ),
    "purchase_order_created": BigQueryTableContract(
        table_name="purchase_order_created",
        source_silver_table="purchase_order_created",
        fields=COMMON_FIELDS
        + (
            BigQueryField("purchase_order_id", "STRING", "REQUIRED", "Purchase order UUID."),
            BigQueryField("procurement_cycle_id", "STRING", "REQUIRED", "Procurement cycle UUID."),
            BigQueryField("branch_id", "STRING", "REQUIRED", "Pharmacy branch UUID."),
            BigQueryField("supplier_id", "STRING", "REQUIRED", "Synthetic supplier UUID."),
            BigQueryField("expected_delivery_on", "DATE", "REQUIRED", "Expected delivery date."),
            BigQueryField("line_count", "INTEGER", "REQUIRED", "Number of PO lines."),
            BigQueryField("ordered_units", "INTEGER", "REQUIRED", "Units ordered."),
            BigQueryField(
                "monetary_values_generated",
                "BOOLEAN",
                "REQUIRED",
                "False until authoritative pricing/cost data is introduced.",
            ),
        ),
        partition_field="event_date",
        clustering_fields=("branch_id", "supplier_id", "purchase_order_id"),
        description="Purchase-order creation facts for the synthetic supplier network.",
    ),
    "goods_receipt_received": BigQueryTableContract(
        table_name="goods_receipt_received",
        source_silver_table="goods_receipt_received",
        fields=COMMON_FIELDS
        + (
            BigQueryField("receipt_id", "STRING", "REQUIRED", "Goods receipt UUID."),
            BigQueryField("purchase_order_id", "STRING", "REQUIRED", "Purchase order UUID."),
            BigQueryField("branch_id", "STRING", "REQUIRED", "Pharmacy branch UUID."),
            BigQueryField("supplier_id", "STRING", "REQUIRED", "Synthetic supplier UUID."),
            BigQueryField("line_count", "INTEGER", "REQUIRED", "Number of received lines."),
            BigQueryField("received_units", "INTEGER", "REQUIRED", "Units received."),
        ),
        partition_field="event_date",
        clustering_fields=("branch_id", "supplier_id", "purchase_order_id"),
        description="Goods-receipt facts linked to purchase orders and suppliers.",
    ),
    "restock_applied": BigQueryTableContract(
        table_name="restock_applied",
        source_silver_table="restock_applied",
        fields=COMMON_FIELDS
        + (
            BigQueryField("movement_id", "STRING", "REQUIRED", "Restock movement UUID."),
            BigQueryField("receipt_id", "STRING", "REQUIRED", "Goods receipt UUID."),
            BigQueryField("purchase_order_id", "STRING", "REQUIRED", "Purchase order UUID."),
            BigQueryField("branch_id", "STRING", "REQUIRED", "Pharmacy branch UUID."),
            BigQueryField("product_id", "STRING", "REQUIRED", "Canonical product UUID."),
            BigQueryField("quantity", "INTEGER", "REQUIRED", "Restocked units."),
            BigQueryField("on_hand_before", "INTEGER", "REQUIRED", "On-hand units before restock."),
            BigQueryField("on_hand_after", "INTEGER", "REQUIRED", "On-hand units after restock."),
            BigQueryField(
                "inventory_version_after", "INTEGER", "REQUIRED", "Inventory version after restock."
            ),
        ),
        partition_field="event_date",
        clustering_fields=("branch_id", "product_id", "purchase_order_id"),
        description="Restock facts applied after goods receipt.",
    ),
}

# Spark types accepted by each BigQuery logical type. Integer payload fields are Spark int,
# while Kafka offsets are Spark bigint/long; both land safely in BigQuery INT64.
SPARK_TYPES_BY_BIGQUERY_TYPE: Final[dict[str, frozenset[str]]] = {
    "STRING": frozenset({"string"}),
    "TIMESTAMP": frozenset({"timestamp"}),
    "DATE": frozenset({"date"}),
    "INTEGER": frozenset({"int", "bigint", "long"}),
    "BOOLEAN": frozenset({"boolean"}),
}

DEFAULT_DATASET_ID: Final[str] = "pharmstock_silver"
DEFAULT_LOCATION: Final[str] = "EU"


def table_contract(table_name: str) -> BigQueryTableContract:
    try:
        return TABLE_CONTRACTS[table_name]
    except KeyError as exc:
        raise ValueError(f"unknown Stage 5A BigQuery table={table_name!r}") from exc


__all__ = [
    "BigQueryField",
    "BigQueryTableContract",
    "COMMON_FIELDS",
    "DEFAULT_DATASET_ID",
    "DEFAULT_LOCATION",
    "SPARK_TYPES_BY_BIGQUERY_TYPE",
    "TABLE_CONTRACTS",
    "table_contract",
]
