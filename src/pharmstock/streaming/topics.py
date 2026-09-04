"""Kafka topic contracts for PharmStock Stage 3A."""

from __future__ import annotations

from dataclasses import dataclass

from pharmstock.domain import DomainEvent


@dataclass(frozen=True, slots=True)
class TopicSpec:
    """One managed Kafka topic used by PharmStock."""

    name: str
    partitions: int
    replication_factor: int = 1
    retention_ms: int = 604_800_000

    @property
    def config(self) -> dict[str, str]:
        return {
            "cleanup.policy": "delete",
            "retention.ms": str(self.retention_ms),
        }


SALES_TOPIC = TopicSpec("pharmstock.sales.v1", partitions=3)
INVENTORY_TOPIC = TopicSpec("pharmstock.inventory.v1", partitions=3)
PROCUREMENT_TOPIC = TopicSpec("pharmstock.procurement.v1", partitions=3)
DEAD_LETTER_TOPIC = TopicSpec(
    "pharmstock.dead-letter.v1",
    partitions=1,
    retention_ms=1_209_600_000,
)

MANAGED_TOPICS: tuple[TopicSpec, ...] = (
    SALES_TOPIC,
    INVENTORY_TOPIC,
    PROCUREMENT_TOPIC,
    DEAD_LETTER_TOPIC,
)


def topic_for_event_type(event_type: str) -> TopicSpec:
    """Return the canonical topic for one versioned domain-event type."""

    if event_type.startswith("sale."):
        return SALES_TOPIC
    if event_type.startswith("inventory."):
        return INVENTORY_TOPIC
    if event_type.startswith(("restock.", "purchase_order.", "goods_receipt.")):
        return PROCUREMENT_TOPIC
    raise ValueError(f"no Kafka topic mapping for event_type={event_type!r}")


def topic_for_event(event: DomainEvent) -> TopicSpec:
    return topic_for_event_type(event.event_type)
