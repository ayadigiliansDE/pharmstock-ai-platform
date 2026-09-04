"""Durable Kafka consumer processing with a SQLite inbox/idempotency ledger.

Stage 3C keeps the source Kafka consumer at-least-once and adds an application-level
inbox ledger keyed by ``event_id``.  Replayed copies of the same validated event are
recorded as duplicates and are not processed twice.  Invalid or failed messages are
written to a durable failure ledger and published to the Kafka dead-letter topic before
source offsets are committed.

The default processing action is the durable inbox insert itself.  If a caller supplies
an external handler, that handler must be idempotent or transactionally coupled to its
own sink because Kafka + SQLite do not form one distributed transaction.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from pharmstock.streaming.kafka import (
    KafkaDeadLetterProducer,
    KafkaEventConsumer,
    RawConsumedKafkaMessage,
)
from pharmstock.streaming.serialization import (
    EventDeserializationError,
    KnownDomainEvent,
    deserialize_event,
    headers_to_dict,
    serialize_event,
)

_FAILURE_NAMESPACE = UUID("58fa80c9-18d0-4454-bf12-3bc3c6f02d66")


class ProcessingStatus(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    FAILED = "failed"


class FailureStage(StrEnum):
    DESERIALIZATION = "deserialization"
    PROCESSING = "processing"
    IDEMPOTENCY = "idempotency"


class IdempotencyConflictError(RuntimeError):
    """Raised when one event_id is reused for different validated event content."""


class DeadLetterEnvelope(BaseModel):
    """Portable DLQ record retaining the failed Kafka source location and raw payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    failure_id: UUID
    failed_at: datetime
    failure_stage: FailureStage
    error_type: str = Field(min_length=1)
    error_message: str = Field(min_length=1)
    source_topic: str = Field(min_length=1)
    source_partition: int = Field(ge=0)
    source_offset: int = Field(ge=0)
    event_id: UUID | None = None
    event_type: str | None = None
    payload_sha256: str = Field(min_length=64, max_length=64)
    key_base64: str | None = None
    payload_base64: str
    headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class ProcessingOutcome:
    status: ProcessingStatus
    topic: str
    partition: int
    offset: int
    event_id: UUID | None = None
    event_type: str | None = None
    failure_id: UUID | None = None
    failure_stage: FailureStage | None = None


@dataclass(frozen=True, slots=True)
class ProcessingLedgerCounts:
    processed: int
    duplicates: int
    failures: int
    dlq_published: int


@dataclass(frozen=True, slots=True)
class _ProcessedEventRecord:
    event_id: UUID
    payload_sha256: str


@dataclass(frozen=True, slots=True)
class _FailureRecord:
    failure_id: UUID
    dlq_published: bool


class DurableInboxStore:
    """SQLite-backed inbox ledger used by one or more local consumer processes."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, timeout=30.0)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._initialize()

    def _initialize(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS processed_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                aggregate_id TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                causation_id TEXT,
                topic TEXT NOT NULL,
                partition_id INTEGER NOT NULL,
                offset_value INTEGER NOT NULL,
                payload_sha256 TEXT NOT NULL,
                processed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS duplicate_messages (
                topic TEXT NOT NULL,
                partition_id INTEGER NOT NULL,
                offset_value INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                PRIMARY KEY (topic, partition_id, offset_value)
            );

            CREATE TABLE IF NOT EXISTS failed_messages (
                failure_id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                partition_id INTEGER NOT NULL,
                offset_value INTEGER NOT NULL,
                event_id TEXT,
                event_type TEXT,
                failure_stage TEXT NOT NULL,
                error_type TEXT NOT NULL,
                error_message TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                dlq_published INTEGER NOT NULL DEFAULT 0,
                failed_at TEXT NOT NULL,
                UNIQUE (topic, partition_id, offset_value)
            );
            """
        )
        self._connection.commit()

    def processed_event(self, event_id: UUID) -> _ProcessedEventRecord | None:
        row = self._connection.execute(
            "SELECT event_id, payload_sha256 FROM processed_events WHERE event_id = ?",
            (str(event_id),),
        ).fetchone()
        if row is None:
            return None
        return _ProcessedEventRecord(
            event_id=UUID(row["event_id"]), payload_sha256=row["payload_sha256"]
        )

    def mark_processed(
        self,
        *,
        event: KnownDomainEvent,
        source: RawConsumedKafkaMessage,
        payload_sha256: str,
    ) -> bool:
        try:
            self._connection.execute(
                """
                INSERT INTO processed_events (
                    event_id, event_type, schema_version, aggregate_id, correlation_id,
                    causation_id, topic, partition_id, offset_value, payload_sha256,
                    processed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(event.event_id),
                    event.event_type,
                    event.schema_version,
                    str(event.aggregate_id),
                    str(event.correlation_id),
                    None if event.causation_id is None else str(event.causation_id),
                    source.topic,
                    source.partition,
                    source.offset,
                    payload_sha256,
                    datetime.now(UTC).isoformat(),
                ),
            )
            self._connection.commit()
            return True
        except sqlite3.IntegrityError:
            self._connection.rollback()
            return False

    def record_duplicate(self, *, event_id: UUID, source: RawConsumedKafkaMessage) -> None:
        self._connection.execute(
            """
            INSERT OR IGNORE INTO duplicate_messages (
                topic, partition_id, offset_value, event_id, observed_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                source.topic,
                source.partition,
                source.offset,
                str(event_id),
                datetime.now(UTC).isoformat(),
            ),
        )
        self._connection.commit()

    def failure_for_source(self, source: RawConsumedKafkaMessage) -> _FailureRecord | None:
        row = self._connection.execute(
            """
            SELECT failure_id, dlq_published
            FROM failed_messages
            WHERE topic = ? AND partition_id = ? AND offset_value = ?
            """,
            (source.topic, source.partition, source.offset),
        ).fetchone()
        if row is None:
            return None
        return _FailureRecord(
            failure_id=UUID(row["failure_id"]), dlq_published=bool(row["dlq_published"])
        )

    def record_failure(self, envelope: DeadLetterEnvelope) -> None:
        self._connection.execute(
            """
            INSERT OR IGNORE INTO failed_messages (
                failure_id, topic, partition_id, offset_value, event_id, event_type,
                failure_stage, error_type, error_message, payload_sha256,
                dlq_published, failed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                str(envelope.failure_id),
                envelope.source_topic,
                envelope.source_partition,
                envelope.source_offset,
                None if envelope.event_id is None else str(envelope.event_id),
                envelope.event_type,
                envelope.failure_stage.value,
                envelope.error_type,
                envelope.error_message,
                envelope.payload_sha256,
                envelope.failed_at.isoformat(),
            ),
        )
        self._connection.commit()

    def mark_dlq_published(self, failure_id: UUID) -> None:
        self._connection.execute(
            "UPDATE failed_messages SET dlq_published = 1 WHERE failure_id = ?",
            (str(failure_id),),
        )
        self._connection.commit()

    def counts(self) -> ProcessingLedgerCounts:
        processed = self._connection.execute("SELECT COUNT(*) FROM processed_events").fetchone()[0]
        duplicates = self._connection.execute(
            "SELECT COUNT(*) FROM duplicate_messages"
        ).fetchone()[0]
        failures = self._connection.execute("SELECT COUNT(*) FROM failed_messages").fetchone()[0]
        dlq_published = self._connection.execute(
            "SELECT COUNT(*) FROM failed_messages WHERE dlq_published = 1"
        ).fetchone()[0]
        return ProcessingLedgerCounts(
            processed=processed,
            duplicates=duplicates,
            failures=failures,
            dlq_published=dlq_published,
        )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> DurableInboxStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_event_hash(event: KnownDomainEvent) -> str:
    return _sha256(serialize_event(event))


def _failure_id(source: RawConsumedKafkaMessage, stage: FailureStage) -> UUID:
    return uuid5(
        _FAILURE_NAMESPACE,
        f"{source.topic}|{source.partition}|{source.offset}|{stage.value}",
    )


def build_dead_letter_envelope(
    *,
    source: RawConsumedKafkaMessage,
    stage: FailureStage,
    error: Exception,
    event: KnownDomainEvent | None = None,
) -> DeadLetterEnvelope:
    return DeadLetterEnvelope(
        failure_id=_failure_id(source, stage),
        failed_at=datetime.now(UTC),
        failure_stage=stage,
        error_type=type(error).__name__,
        error_message=str(error),
        source_topic=source.topic,
        source_partition=source.partition,
        source_offset=source.offset,
        event_id=None if event is None else event.event_id,
        event_type=None if event is None else event.event_type,
        payload_sha256=_sha256(source.value),
        key_base64=(
            None if source.key is None else base64.b64encode(source.key).decode("ascii")
        ),
        payload_base64=base64.b64encode(source.value).decode("ascii"),
        headers=headers_to_dict(source.headers),
    )


def deserialize_dead_letter(payload: bytes) -> DeadLetterEnvelope:
    return DeadLetterEnvelope.model_validate_json(payload)


class DurableKafkaProcessor:
    """Consume one Kafka message at a time with durable dedupe and DLQ handling."""

    def __init__(
        self,
        *,
        consumer: KafkaEventConsumer,
        store: DurableInboxStore,
        dead_letter_producer: KafkaDeadLetterProducer,
        handler: Callable[[KnownDomainEvent], None] | None = None,
    ) -> None:
        self.consumer = consumer
        self.store = store
        self.dead_letter_producer = dead_letter_producer
        self.handler = handler

    def process_one(self, *, timeout_seconds: float = 30.0) -> ProcessingOutcome:
        source = self.consumer.consume_raw_one(timeout_seconds=timeout_seconds, commit=False)
        return self.process_message(source)

    def process_message(self, source: RawConsumedKafkaMessage) -> ProcessingOutcome:
        existing_failure = self.store.failure_for_source(source)
        if existing_failure is not None and existing_failure.dlq_published:
            self.consumer.commit_message(source)
            return ProcessingOutcome(
                status=ProcessingStatus.FAILED,
                topic=source.topic,
                partition=source.partition,
                offset=source.offset,
                failure_id=existing_failure.failure_id,
            )

        try:
            event = deserialize_event(source.value)
        except EventDeserializationError as exc:
            return self._fail(source=source, stage=FailureStage.DESERIALIZATION, error=exc)

        canonical_hash = _canonical_event_hash(event)
        prior = self.store.processed_event(event.event_id)
        if prior is not None:
            if prior.payload_sha256 != canonical_hash:
                error = IdempotencyConflictError(
                    f"event_id {event.event_id} was previously processed with different content"
                )
                return self._fail(
                    source=source,
                    stage=FailureStage.IDEMPOTENCY,
                    error=error,
                    event=event,
                )
            self.store.record_duplicate(event_id=event.event_id, source=source)
            self.consumer.commit_message(source)
            return ProcessingOutcome(
                status=ProcessingStatus.DUPLICATE,
                topic=source.topic,
                partition=source.partition,
                offset=source.offset,
                event_id=event.event_id,
                event_type=event.event_type,
            )

        try:
            if self.handler is not None:
                self.handler(event)
        except Exception as exc:  # application handlers expose application-specific failures
            return self._fail(
                source=source,
                stage=FailureStage.PROCESSING,
                error=exc,
                event=event,
            )

        inserted = self.store.mark_processed(
            event=event,
            source=source,
            payload_sha256=canonical_hash,
        )
        if not inserted:
            prior = self.store.processed_event(event.event_id)
            if prior is None or prior.payload_sha256 != canonical_hash:
                error = IdempotencyConflictError(
                    f"event_id {event.event_id} collided during durable inbox insert"
                )
                return self._fail(
                    source=source,
                    stage=FailureStage.IDEMPOTENCY,
                    error=error,
                    event=event,
                )
            self.store.record_duplicate(event_id=event.event_id, source=source)
            status = ProcessingStatus.DUPLICATE
        else:
            status = ProcessingStatus.PROCESSED

        self.consumer.commit_message(source)
        return ProcessingOutcome(
            status=status,
            topic=source.topic,
            partition=source.partition,
            offset=source.offset,
            event_id=event.event_id,
            event_type=event.event_type,
        )

    def _fail(
        self,
        *,
        source: RawConsumedKafkaMessage,
        stage: FailureStage,
        error: Exception,
        event: KnownDomainEvent | None = None,
    ) -> ProcessingOutcome:
        envelope = build_dead_letter_envelope(
            source=source,
            stage=stage,
            error=error,
            event=event,
        )
        self.store.record_failure(envelope)
        existing = self.store.failure_for_source(source)
        if existing is None or not existing.dlq_published:
            self.dead_letter_producer.publish(
                envelope.model_dump_json().encode("utf-8"),
                key=str(envelope.failure_id).encode("ascii"),
                extra_headers=(
                    ("failure-stage", stage.value.encode("ascii")),
                    ("source-topic", source.topic.encode("utf-8")),
                ),
            )
            self.store.mark_dlq_published(envelope.failure_id)
        self.consumer.commit_message(source)
        return ProcessingOutcome(
            status=ProcessingStatus.FAILED,
            topic=source.topic,
            partition=source.partition,
            offset=source.offset,
            event_id=None if event is None else event.event_id,
            event_type=None if event is None else event.event_type,
            failure_id=envelope.failure_id,
            failure_stage=stage,
        )


def processing_summary(outcomes: list[ProcessingOutcome]) -> dict[str, int]:
    counts = {status.value: 0 for status in ProcessingStatus}
    for outcome in outcomes:
        counts[outcome.status.value] += 1
    return counts


def write_processing_summary(path: Path, *, outcomes: list[ProcessingOutcome]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "generated_at": datetime.now(UTC).isoformat(),
        "counts": processing_summary(outcomes),
        "messages": len(outcomes),
    }
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")
