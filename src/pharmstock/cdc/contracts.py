"""Stage 7F Debezium CDC contracts for PostgreSQL -> Kafka."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Final

from pharmstock.onprem import (
    CDC_PLUGIN,
    CDC_PUBLICATION,
    CDC_SLOT,
    CDC_TABLES,
    CDC_TOPIC_PREFIX,
    DEBEZIUM_COMPATIBLE_RELEASE,
    POSTGRES_CDC_USER,
    POSTGRES_DATABASE,
)

DEBEZIUM_IMAGE: Final[str] = "quay.io/debezium/connect:3.6"
DEBEZIUM_RELEASE: Final[str] = DEBEZIUM_COMPATIBLE_RELEASE
CONNECTOR_NAME: Final[str] = "pharmstock-postgres-cdc"
CONNECT_REST_URL: Final[str] = "http://localhost:8083"
CONNECT_INTERNAL_BOOTSTRAP: Final[str] = "kafka:19092"
POSTGRES_INTERNAL_HOST: Final[str] = "postgres"
POSTGRES_INTERNAL_PORT: Final[int] = 5432
SNAPSHOT_MODE: Final[str] = "no_data"
CDC_TOPIC_PARTITIONS: Final[int] = 3
CDC_TOPIC_RETENTION_MS: Final[int] = 604_800_000


@dataclass(frozen=True, slots=True)
class CdcTopicSpec:
    """One table-specific Debezium topic."""

    table: str
    topic: str
    partitions: int = CDC_TOPIC_PARTITIONS
    replication_factor: int = 1
    retention_ms: int = CDC_TOPIC_RETENTION_MS

    @property
    def config(self) -> dict[str, str]:
        return {
            "cleanup.policy": "delete",
            "retention.ms": str(self.retention_ms),
        }


def topic_name(table: str) -> str:
    """Return the canonical Debezium topic name for a fully-qualified PostgreSQL table."""

    return f"{CDC_TOPIC_PREFIX}.{table}"


CDC_TOPICS: Final[tuple[CdcTopicSpec, ...]] = tuple(
    CdcTopicSpec(table=table, topic=topic_name(table)) for table in CDC_TABLES
)


def connector_config(cdc_password: str) -> dict[str, str]:
    """Build the canonical connector configuration without persisting the secret."""

    if not cdc_password:
        raise ValueError("CDC password cannot be empty")
    return {
        "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
        "tasks.max": "1",
        "database.hostname": POSTGRES_INTERNAL_HOST,
        "database.port": str(POSTGRES_INTERNAL_PORT),
        "database.user": POSTGRES_CDC_USER,
        "database.password": cdc_password,
        "database.dbname": POSTGRES_DATABASE,
        "topic.prefix": CDC_TOPIC_PREFIX,
        "plugin.name": CDC_PLUGIN,
        "slot.name": CDC_SLOT,
        "publication.name": CDC_PUBLICATION,
        "publication.autocreate.mode": "disabled",
        "snapshot.mode": SNAPSHOT_MODE,
        "table.include.list": ",".join(CDC_TABLES),
        "tombstones.on.delete": "false",
        "decimal.handling.mode": "string",
        "heartbeat.interval.ms": "10000",
        "provide.transaction.metadata": "true",
    }


def redacted_connector_config(cdc_password: str) -> dict[str, str]:
    """Return the connector configuration with the password removed from inspectable artifacts."""

    config = connector_config(cdc_password)
    config["database.password"] = "<REDACTED>"
    return config


def cdc_contract() -> dict[str, object]:
    """Serializable Stage 7F boundary contract."""

    return {
        "stage": "7F",
        "flow": "POSTGRESQL_LOGICAL_WAL -> DEBEZIUM -> KAFKA",
        "debezium": {
            "image": DEBEZIUM_IMAGE,
            "release": DEBEZIUM_RELEASE,
            "connector_name": CONNECTOR_NAME,
            "rest_url": CONNECT_REST_URL,
        },
        "postgres": {
            "database": POSTGRES_DATABASE,
            "cdc_user": POSTGRES_CDC_USER,
            "plugin": CDC_PLUGIN,
            "publication": CDC_PUBLICATION,
            "slot": CDC_SLOT,
        },
        "snapshot_boundary": {
            "mode": SNAPSHOT_MODE,
            "historical_stage7e_rows_republished": False,
            "reason": (
                "Stage 7F validates and starts low-latency CDC for new operational mutations; "
                "Stage 7G performs the controlled historical warehouse rebuild."
            ),
        },
        "topics": [asdict(topic) for topic in CDC_TOPICS],
        "truth_boundary": {
            "event_payload": "SOURCE_DATABASE_CHANGE_EVENT",
            "transport": "KAFKA_JSON_DEBEZIUM_ENVELOPE",
            "cloud_mutation": False,
        },
    }
