"""Thin Kafka transport adapters around validated PharmStock domain events.

The domain layer remains Kafka-agnostic.  This module is the infrastructure boundary.
Imports from ``confluent_kafka`` are intentionally lazy so pure unit tests do not need
an active broker.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from importlib import import_module
from typing import Any
from uuid import UUID

from pharmstock.domain import DomainEvent
from pharmstock.streaming.serialization import (
    KnownDomainEvent,
    deserialize_event,
    event_headers,
    event_key,
    serialize_event,
)
from pharmstock.streaming.topics import (
    DEAD_LETTER_TOPIC,
    MANAGED_TOPICS,
    TopicSpec,
    topic_for_event,
)


class KafkaDependencyError(RuntimeError):
    """Raised when the declared Python Kafka client is not installed."""


class KafkaUnavailableError(RuntimeError):
    """Raised when the configured broker cannot be reached."""


class KafkaPublishError(RuntimeError):
    """Raised when a producer cannot confirm delivery."""


@dataclass(frozen=True, slots=True)
class KafkaSettings:
    bootstrap_servers: str = "localhost:9092"
    client_id: str = "pharmstock-local"
    request_timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls) -> KafkaSettings:
        bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092").strip()
        client_id = os.getenv("KAFKA_CLIENT_ID", "pharmstock-local").strip()
        if not bootstrap_servers:
            raise ValueError("KAFKA_BOOTSTRAP_SERVERS cannot be empty")
        if not client_id:
            raise ValueError("KAFKA_CLIENT_ID cannot be empty")
        return cls(bootstrap_servers=bootstrap_servers, client_id=client_id)


@dataclass(frozen=True, slots=True)
class PublishedKafkaEvent:
    event_id: UUID
    topic: str
    partition: int
    offset: int


@dataclass(frozen=True, slots=True)
class RawConsumedKafkaMessage:
    topic: str
    partition: int
    offset: int
    key: bytes | None
    value: bytes
    headers: tuple[tuple[str, bytes | None], ...]


@dataclass(frozen=True, slots=True)
class ConsumedKafkaEvent:
    event: KnownDomainEvent
    topic: str
    partition: int
    offset: int
    key: bytes | None
    headers: tuple[tuple[str, bytes | None], ...]


def _load(module_name: str) -> Any:
    try:
        return import_module(module_name)
    except ModuleNotFoundError as exc:
        raise KafkaDependencyError(
            "Kafka support requires confluent-kafka; run pip install -e \".[dev]\""
        ) from exc


class KafkaAdmin:
    def __init__(self, settings: KafkaSettings) -> None:
        self.settings = settings

    def _client(self) -> Any:
        admin = _load("confluent_kafka.admin")
        return admin.AdminClient(
            {
                "bootstrap.servers": self.settings.bootstrap_servers,
                "client.id": f"{self.settings.client_id}-admin",
            }
        )

    def wait_until_available(self, *, timeout_seconds: float = 45.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                self._client().list_topics(timeout=2.0)
                return
            except Exception as exc:  # broker client exposes library-specific exceptions
                last_error = exc
                time.sleep(1.0)
        raise KafkaUnavailableError(
            f"Kafka is not reachable at {self.settings.bootstrap_servers}"
        ) from last_error

    def ensure_topics(self, specs: tuple[TopicSpec, ...] = MANAGED_TOPICS) -> tuple[str, ...]:
        admin_module = _load("confluent_kafka.admin")
        client = self._client()
        metadata = client.list_topics(timeout=self.settings.request_timeout_seconds)
        existing = set(metadata.topics)
        missing = [spec for spec in specs if spec.name not in existing]
        if missing:
            futures = client.create_topics(
                [
                    admin_module.NewTopic(
                        spec.name,
                        num_partitions=spec.partitions,
                        replication_factor=spec.replication_factor,
                        config=spec.config,
                    )
                    for spec in missing
                ],
                request_timeout=self.settings.request_timeout_seconds,
            )
            for topic_name, future in futures.items():
                try:
                    future.result(timeout=self.settings.request_timeout_seconds)
                except Exception as exc:
                    # A parallel local bootstrap may have won the create race.
                    refreshed = client.list_topics(
                        timeout=self.settings.request_timeout_seconds
                    ).topics
                    if topic_name not in refreshed:
                        raise KafkaUnavailableError(
                            f"failed to create Kafka topic {topic_name}"
                        ) from exc

        refreshed = client.list_topics(timeout=self.settings.request_timeout_seconds).topics
        absent = [spec.name for spec in specs if spec.name not in refreshed]
        if absent:
            raise KafkaUnavailableError(f"managed Kafka topics missing after bootstrap: {absent}")
        return tuple(spec.name for spec in specs)

    def topic_partitions(self) -> dict[str, int]:
        metadata = self._client().list_topics(timeout=self.settings.request_timeout_seconds)
        return {
            spec.name: len(metadata.topics[spec.name].partitions)
            for spec in MANAGED_TOPICS
            if spec.name in metadata.topics
        }


class KafkaEventProducer:
    def __init__(self, settings: KafkaSettings) -> None:
        kafka = _load("confluent_kafka")
        self._producer = kafka.Producer(
            {
                "bootstrap.servers": settings.bootstrap_servers,
                "client.id": f"{settings.client_id}-producer",
                "enable.idempotence": True,
                "acks": "all",
                "compression.type": "zstd",
                "linger.ms": 5,
            }
        )

    def publish(self, event: DomainEvent, *, timeout_seconds: float = 10.0) -> PublishedKafkaEvent:
        return self.publish_many((event,), timeout_seconds=timeout_seconds)[0]

    def publish_many(
        self,
        events: tuple[DomainEvent, ...],
        *,
        timeout_seconds: float = 30.0,
    ) -> tuple[PublishedKafkaEvent, ...]:
        if not events:
            return ()
        delivered: dict[UUID, PublishedKafkaEvent] = {}
        errors: list[str] = []

        def callback_for(event: DomainEvent):
            def on_delivery(error: Any, message: Any) -> None:
                if error is not None:
                    errors.append(str(error))
                    return
                delivered[event.event_id] = PublishedKafkaEvent(
                    event_id=event.event_id,
                    topic=message.topic(),
                    partition=message.partition(),
                    offset=message.offset(),
                )

            return on_delivery

        for event in events:
            spec = topic_for_event(event)
            self._producer.produce(
                spec.name,
                key=event_key(event),
                value=serialize_event(event),
                headers=event_headers(event),
                on_delivery=callback_for(event),
            )
            self._producer.poll(0)

        remaining = self._producer.flush(timeout_seconds)
        if errors:
            raise KafkaPublishError(errors[0])
        if remaining or len(delivered) != len(events):
            raise KafkaPublishError(
                f"Kafka confirmed {len(delivered)}/{len(events)} events before timeout"
            )
        return tuple(delivered[event.event_id] for event in events)


class KafkaDeadLetterProducer:
    """Low-level publisher for invalid records that cannot become DomainEvent objects."""

    def __init__(self, settings: KafkaSettings) -> None:
        kafka = _load("confluent_kafka")
        self._producer = kafka.Producer(
            {
                "bootstrap.servers": settings.bootstrap_servers,
                "client.id": f"{settings.client_id}-dlq-producer",
                "enable.idempotence": True,
                "acks": "all",
                "compression.type": "zstd",
            }
        )

    def publish(
        self,
        payload: bytes,
        *,
        key: bytes | None = None,
        extra_headers: tuple[tuple[str, bytes], ...] = (),
        timeout_seconds: float = 10.0,
    ) -> None:
        errors: list[str] = []
        delivered = False

        def on_delivery(error: Any, _message: Any) -> None:
            nonlocal delivered
            if error is not None:
                errors.append(str(error))
                return
            delivered = True

        self._producer.produce(
            DEAD_LETTER_TOPIC.name,
            key=key,
            value=payload,
            headers=[
                ("content-type", b"application/json"),
                ("source", b"pharmstock-ai-platform"),
                *extra_headers,
            ],
            on_delivery=on_delivery,
        )
        remaining = self._producer.flush(timeout_seconds)
        if errors:
            raise KafkaPublishError(errors[0])
        if remaining or not delivered:
            raise KafkaPublishError("Kafka dead-letter delivery was not confirmed")


class KafkaEventConsumer:
    def __init__(
        self,
        settings: KafkaSettings,
        *,
        group_id: str,
        topics: tuple[str, ...],
        auto_offset_reset: str = "latest",
    ) -> None:
        kafka = _load("confluent_kafka")
        self._consumer = kafka.Consumer(
            {
                "bootstrap.servers": settings.bootstrap_servers,
                "client.id": f"{settings.client_id}-consumer",
                "group.id": group_id,
                "auto.offset.reset": auto_offset_reset,
                "enable.auto.commit": False,
            }
        )
        self._consumer.subscribe(list(topics))

    def wait_for_assignment(self, *, timeout_seconds: float = 15.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            self._consumer.poll(0.2)
            if self._consumer.assignment():
                return
        raise KafkaUnavailableError("consumer did not receive a partition assignment")

    def consume_raw_one(
        self, *, timeout_seconds: float = 30.0, commit: bool = True
    ) -> RawConsumedKafkaMessage:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            message = self._consumer.poll(min(1.0, max(deadline - time.monotonic(), 0.0)))
            if message is None:
                continue
            if message.error():
                raise KafkaUnavailableError(str(message.error()))
            raw = RawConsumedKafkaMessage(
                topic=message.topic(),
                partition=message.partition(),
                offset=message.offset(),
                key=message.key(),
                value=b"" if message.value() is None else bytes(message.value()),
                headers=tuple(message.headers() or ()),
            )
            if commit:
                self.commit_message(raw)
            return raw
        raise KafkaUnavailableError("timed out waiting for a Kafka event")

    def consume_one(
        self, *, timeout_seconds: float = 30.0, commit: bool = True
    ) -> ConsumedKafkaEvent:
        raw = self.consume_raw_one(timeout_seconds=timeout_seconds, commit=False)
        result = ConsumedKafkaEvent(
            event=deserialize_event(raw.value),
            topic=raw.topic,
            partition=raw.partition,
            offset=raw.offset,
            key=raw.key,
            headers=raw.headers,
        )
        if commit:
            self.commit_message(raw)
        return result

    def commit_message(self, message: RawConsumedKafkaMessage) -> None:
        kafka = _load("confluent_kafka")
        self._consumer.commit(
            offsets=[kafka.TopicPartition(message.topic, message.partition, message.offset + 1)],
            asynchronous=False,
        )

    def commit(self) -> None:
        self._consumer.commit(asynchronous=False)

    def close(self) -> None:
        self._consumer.close()

    def __enter__(self) -> KafkaEventConsumer:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
