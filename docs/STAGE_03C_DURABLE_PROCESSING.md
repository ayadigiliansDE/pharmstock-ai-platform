# Stage 3C — Durable Kafka Consumer Processing + Idempotency

## Purpose

Stage 3B proved that simulator events can move through Kafka. Stage 3C changes the consumer from a console observer into a durable processing boundary.

```text
Kafka business topic
       ↓
raw message
       ↓
contract validation
       ↓
SQLite durable inbox lookup by event_id
       ├── unseen + valid ──> processed_events ──> commit source offset
       ├── seen + same canonical hash ──> duplicate_messages ──> commit source offset
       ├── seen + different canonical hash ──> idempotency failure ──> DLQ ──> commit
       └── invalid / handler failure ──> failed_messages ──> DLQ ──> commit
```

## Durable state

The local checkpoint uses SQLite because it is built into Python and makes the durability contract visible without adding another infrastructure service before Spark/warehouse work begins.

The database contains:

- `processed_events`: one row per successfully accepted `event_id`.
- `duplicate_messages`: each later Kafka message carrying an already processed event with the same canonical content.
- `failed_messages`: validation, handler, or idempotency-conflict failures plus whether DLQ publication was confirmed.

SQLite runs with WAL journaling and `synchronous=FULL` for the local checkpoint.

## Idempotency contract

`event_id` is the primary idempotency key. The processor also stores SHA-256 of the canonical validated event JSON.

Therefore:

```text
same event_id + same canonical content
= duplicate -> skip processing

same event_id + different canonical content
= conflict -> DLQ
```

This is stronger than checking `event_id` alone because identity corruption is not silently ignored.

## Offset/commit rule

Auto-commit remains disabled. A source Kafka offset is committed only after the processor has reached one durable outcome:

1. processed and recorded in the inbox;
2. duplicate and recorded in the duplicate ledger; or
3. failed, persisted, and confirmed published to the DLQ.

## Delivery semantics

This stage does **not** claim globally distributed exactly-once processing.

The precise contract is:

```text
Kafka delivery: at least once
Application processing: durable event_id inbox deduplication
DLQ delivery: confirmed before source offset commit
```

The default processing action is the inbox insert itself. If a later stage adds an external handler (database, API, filesystem, etc.), that handler must be idempotent or transactionally coupled to its sink. Kafka and SQLite are not one distributed transaction.

## Dead-letter envelope

DLQ records retain:

- deterministic failure ID for the Kafka source location + failure stage;
- source topic / partition / offset;
- optional validated event ID/type;
- error stage/type/message;
- SHA-256 of the raw payload;
- Base64-encoded raw payload and key;
- source headers.

This preserves enough evidence to diagnose or replay failures later without pretending the invalid message was a valid DomainEvent.

## Why this comes before Spark

Spark will eventually consume the operational stream for scalable transformation. Stage 3C first establishes the application-level rules for duplicate identities, poison messages, commit timing, and DLQ handling. Those semantics should be explicit before another distributed processing layer is introduced.
