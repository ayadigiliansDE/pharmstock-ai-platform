import json

from pharmstock.analytics import BRONZE_EVENT_TOPICS, BRONZE_TOPICS, validate_bronze_envelope
from pharmstock.streaming import INVENTORY_TOPIC, PROCUREMENT_TOPIC, SALES_TOPIC

EVENT_ID = "40000000-0000-4000-8000-000000000001"
AGGREGATE_ID = "40000000-0000-4000-8000-000000000002"
CORRELATION_ID = "40000000-0000-4000-8000-000000000003"
CAUSATION_ID = "40000000-0000-4000-8000-000000000004"


def _payload(**overrides: object) -> bytes:
    event = {
        "event_id": EVENT_ID,
        "event_type": "sale.units_fulfilled",
        "schema_version": "1.0",
        "aggregate_type": "demand_line",
        "aggregate_id": AGGREGATE_ID,
        "occurred_at": "2026-08-22T18:00:00+00:00",
        "recorded_at": "2026-08-22T18:00:01+00:00",
        "correlation_id": CORRELATION_ID,
        "causation_id": CAUSATION_ID,
        "payload": {"requested_quantity": 2, "fulfilled_quantity": 2},
    }
    event.update(overrides)
    return json.dumps(event).encode("utf-8")


def test_bronze_topic_constants_match_kafka_contracts() -> None:
    assert BRONZE_TOPICS == (SALES_TOPIC.name, INVENTORY_TOPIC.name, PROCUREMENT_TOPIC.name)
    assert BRONZE_EVENT_TOPICS["restock.applied"] == PROCUREMENT_TOPIC.name


def test_valid_common_envelope_is_accepted() -> None:
    result = validate_bronze_envelope(
        _payload(), topic=SALES_TOPIC.name, key=AGGREGATE_ID.encode("ascii")
    )

    assert result.is_valid is True
    assert result.error is None
    assert result.event_type == "sale.units_fulfilled"
    assert result.event_id == EVENT_ID


def test_malformed_json_is_quarantined() -> None:
    result = validate_bronze_envelope(
        b'{"event_type":', topic=SALES_TOPIC.name, key=AGGREGATE_ID.encode("ascii")
    )

    assert result.error == "malformed_json"


def test_non_object_json_is_quarantined() -> None:
    result = validate_bronze_envelope(
        b"[]", topic=SALES_TOPIC.name, key=AGGREGATE_ID.encode("ascii")
    )

    assert result.error == "json_not_object"


def test_unknown_event_type_is_quarantined() -> None:
    result = validate_bronze_envelope(
        _payload(event_type="unknown.event"),
        topic=SALES_TOPIC.name,
        key=AGGREGATE_ID.encode("ascii"),
    )

    assert result.error == "unknown_event_type"


def test_wrong_topic_for_known_event_is_quarantined() -> None:
    result = validate_bronze_envelope(
        _payload(), topic=INVENTORY_TOPIC.name, key=AGGREGATE_ID.encode("ascii")
    )

    assert result.error == "topic_event_type_mismatch"


def test_unsupported_schema_version_is_quarantined() -> None:
    result = validate_bronze_envelope(
        _payload(schema_version="2.0"),
        topic=SALES_TOPIC.name,
        key=AGGREGATE_ID.encode("ascii"),
    )

    assert result.error == "unsupported_schema_version"



def test_aggregate_type_is_required() -> None:
    result = validate_bronze_envelope(
        _payload(aggregate_type=""),
        topic=SALES_TOPIC.name,
        key=AGGREGATE_ID.encode("ascii"),
    )

    assert result.error == "invalid_aggregate_type"

def test_invalid_uuid_is_quarantined() -> None:
    result = validate_bronze_envelope(
        _payload(event_id="not-a-uuid"),
        topic=SALES_TOPIC.name,
        key=AGGREGATE_ID.encode("ascii"),
    )

    assert result.error == "invalid_event_id"


def test_kafka_key_must_match_aggregate_id() -> None:
    result = validate_bronze_envelope(
        _payload(), topic=SALES_TOPIC.name, key=b"40000000-0000-4000-8000-000000000099"
    )

    assert result.error == "kafka_key_mismatch"


def test_timestamps_must_be_timezone_aware() -> None:
    result = validate_bronze_envelope(
        _payload(occurred_at="2026-08-22T18:00:00"),
        topic=SALES_TOPIC.name,
        key=AGGREGATE_ID.encode("ascii"),
    )

    assert result.error == "invalid_occurred_at"


def test_payload_must_remain_a_json_object() -> None:
    result = validate_bronze_envelope(
        _payload(payload=[1, 2, 3]),
        topic=SALES_TOPIC.name,
        key=AGGREGATE_ID.encode("ascii"),
    )

    assert result.error == "payload_not_object"

def test_stage4a_spark_job_is_python_310_compatible() -> None:
    import ast
    from pathlib import Path

    source = Path("spark/jobs/stage4a_bronze.py").read_text(encoding="utf-8")
    ast.parse(source, filename="stage4a_bronze.py", feature_version=(3, 10))
    assert "from datetime import UTC" not in source
    assert "datetime.now(timezone.utc)" in source

def test_stage4a_event_type_membership_expands_isin_arguments() -> None:
    from pathlib import Path

    source = Path("spark/jobs/stage4a_bronze.py").read_text(encoding="utf-8")
    assert ".isin(*tuple(BRONZE_EVENT_TOPICS))" in source
    assert ".isin(tuple(BRONZE_EVENT_TOPICS))" not in source

