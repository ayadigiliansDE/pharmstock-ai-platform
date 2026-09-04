from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pharmstock.ml.stage7k5 import (
    ML_OUTPUT_TOPICS,
    MONITORED_CDC_TOPICS,
    STAGE7K5_VERSION,
    alert_is_actionable,
    decode_debezium_change,
    prediction_event_id,
    source_event_id,
    stage7k5_contract,
    stockout_severity,
)
from scripts.run_checkpoint import checkpoint_command


def _payload(*, schema: str = "pos", table: str = "demand_attempt") -> bytes:
    return json.dumps(
        {
            "before": None,
            "after": {
                "branch_id": "11111111-1111-1111-1111-111111111111",
                "product_id": "22222222-2222-2222-2222-222222222222",
            },
            "source": {"schema": schema, "table": table, "ts_ms": 123456789},
            "op": "c",
            "ts_ms": 123456790,
        }
    ).encode()


def test_stage7k5_contract_is_local_durable_and_no_cloud_mutation() -> None:
    contract = stage7k5_contract()
    assert STAGE7K5_VERSION == "0.35.2"
    assert contract["runtime"] == "CDC_TRIGGERED_POSTGRES_READ_THROUGH_INFERENCE"
    assert contract["cold_start_policy"] == "NO_KAFKA_HISTORY_DEPENDENCY"
    assert contract["delivery"]["prediction_outbox"] is True
    assert contract["delivery"]["cross_system_exactly_once_claimed"] is False
    assert contract["cloud_mutation"] is False
    assert contract["bigquery_write"] is False
    assert contract["model_retraining_per_event"] is False


def test_stage7k5_monitors_demand_and_operational_feature_changes() -> None:
    assert "pharmstock.ops.pos.demand_attempt" in MONITORED_CDC_TOPICS
    assert "pharmstock.ops.inventory.inventory_position" in MONITORED_CDC_TOPICS
    assert "pharmstock.ops.inventory.stock_batch" in MONITORED_CDC_TOPICS
    assert "pharmstock.ops.procurement.purchase_order" in MONITORED_CDC_TOPICS
    assert "pharmstock.ops.procurement.supplier" in MONITORED_CDC_TOPICS
    assert "pharmstock.ops.pos.payment" not in MONITORED_CDC_TOPICS


def test_stage7k5_output_topics_are_keyed_compacted_decision_streams() -> None:
    assert len(ML_OUTPUT_TOPICS) == 5
    names = {item.name for item in ML_OUTPUT_TOPICS}
    assert "pharmstock.ml.demand_forecasts" in names
    assert "pharmstock.ml.stockout_predictions" in names
    assert "pharmstock.ml.reorder_recommendations" in names
    assert "pharmstock.ml.expiry_alerts" in names
    for item in ML_OUTPUT_TOPICS:
        if item.name != "pharmstock.ml.model_events":
            assert "compact" in item.cleanup_policy


def test_debezium_decoder_accepts_schemaless_and_wrapped_envelopes() -> None:
    topic = "pharmstock.ops.pos.demand_attempt"
    change = decode_debezium_change(_payload(), topic=topic, partition=1, offset=20)
    assert change.table == "pos.demand_attempt"
    assert change.row["product_id"].startswith("2222")
    wrapped = json.dumps({"schema": {}, "payload": json.loads(_payload())}).encode()
    wrapped_change = decode_debezium_change(wrapped, topic=topic, partition=1, offset=21)
    assert wrapped_change.table == "pos.demand_attempt"
    assert wrapped_change.event_id != change.event_id


def test_debezium_decoder_rejects_topic_source_mismatch() -> None:
    with pytest.raises(ValueError, match="topic/source mismatch"):
        decode_debezium_change(
            _payload(schema="inventory", table="stock_batch"),
            topic="pharmstock.ops.pos.demand_attempt",
            partition=0,
            offset=1,
        )


def test_online_event_ids_are_deterministic_and_entity_specific() -> None:
    first = source_event_id("topic", 2, 99)
    assert first == source_event_id("topic", 2, 99)
    assert first != source_event_id("topic", 2, 100)
    a = prediction_event_id(first, "stockout_risk", "BRANCH_PRODUCT", "b|p")
    b = prediction_event_id(first, "reorder_recommendation", "BRANCH_PRODUCT", "b|p")
    assert a != b


def test_stockout_severity_is_relative_to_rare_event_threshold() -> None:
    threshold = 0.002
    assert stockout_severity(0.0019, threshold, False) == "NORMAL"
    assert stockout_severity(0.0021, threshold, True) == "WATCH"
    assert stockout_severity(0.0041, threshold, True) == "MEDIUM"
    assert stockout_severity(0.0081, threshold, True) == "HIGH"
    assert stockout_severity(0.0161, threshold, True) == "CRITICAL"


def test_alert_cooldown_suppresses_duplicates_but_not_escalation() -> None:
    now = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    assert not alert_is_actionable(
        predicted_positive=True,
        severity="HIGH",
        previous_severity="HIGH",
        previous_alert_at=now - timedelta(hours=1),
        now=now,
        cooldown_seconds=6 * 3600,
    )
    assert alert_is_actionable(
        predicted_positive=True,
        severity="CRITICAL",
        previous_severity="HIGH",
        previous_alert_at=now - timedelta(minutes=1),
        now=now,
        cooldown_seconds=6 * 3600,
    )
    assert not alert_is_actionable(
        predicted_positive=False,
        severity="NORMAL",
        previous_severity="CRITICAL",
        previous_alert_at=None,
        now=now,
        cooldown_seconds=0,
    )


def test_prediction_store_is_isolated_from_debezium_publication() -> None:
    sql = Path("infra/docker/postgres/sql/009_stage7k5_online_ml.sql").read_text(
        encoding="utf-8"
    )
    assert "CREATE SCHEMA IF NOT EXISTS mlops" in sql
    assert "CREATE TABLE IF NOT EXISTS mlops.prediction_outbox" in sql
    assert "CREATE TABLE IF NOT EXISTS mlops.online_source_quarantine" in sql
    assert "CREATE TABLE IF NOT EXISTS mlops.latest_demand_forecast" in sql
    assert "CREATE TABLE IF NOT EXISTS mlops.latest_branch_product_decision" in sql
    assert "CREATE TABLE IF NOT EXISTS mlops.latest_expiry_risk" in sql
    assert "mlops schema must not be part of pharmstock_cdc_publication" in sql
    assert "ADD TABLE mlops." not in sql


def test_worker_uses_read_through_features_and_manual_source_commit() -> None:
    source = Path("ml/stage7k5/worker.py").read_text(encoding="utf-8")
    assert "FROM pos.demand_attempt" in source
    assert "FROM inventory.inventory_position" in source
    assert "mlops.prediction_outbox" in source
    assert '"enable.auto.commit": False' in source
    assert "consumer.commit(message=message, asynchronous=False)" in source
    assert "_publish_pending(conn, producer)" in source
    assert "auto.offset.reset\": \"latest" in source


def test_serving_exposes_model_operating_threshold_for_online_alerts() -> None:
    source = Path("ml/stage7k/serve.py").read_text(encoding="utf-8")
    assert 'threshold = getattr(model, "threshold", None)' in source
    assert '"threshold": _metadata.get(spec.key, {}).get("threshold")' in source


def test_stage7k5_compose_is_local_and_depends_on_stage7k_serving() -> None:
    compose = Path("infra/docker/docker-compose.stage7k5.yml").read_text(encoding="utf-8")
    assert "pharmstock-stage7k5-online" in compose
    assert "KAFKA_BOOTSTRAP_SERVERS: kafka:19092" in compose
    assert "PHARMSTOCK_POSTGRES_HOST: postgres" in compose
    assert "PHARMSTOCK_ML_SERVING_URI: http://model-serving:8090" in compose
    assert "model-serving:" in compose
    assert "PHARMSTOCK_BQ_PROJECT" not in compose


def test_stage7k5_checkpoint_is_registered() -> None:
    assert checkpoint_command("7k5")[1:] == ["scripts/run_stage7k5.py"]


def test_stage7k5_v0352_adds_runtime_reliability_contract() -> None:
    contract = stage7k5_contract()
    reliability = contract["reliability"]
    assert reliability["docker_healthcheck"] is True
    assert reliability["durable_invalid_cdc_quarantine"] is True
    assert reliability["processing_retry"] == "BOUNDED_EXPONENTIAL_BACKOFF"
    assert reliability["heartbeat_max_age_seconds"] == 45
    assert reliability["max_pending_outbox"] == 1000
    assert reliability["max_pending_outbox_age_seconds"] == 300


def test_stage7k5_worker_quarantines_invalid_cdc_and_bounds_retry_backoff() -> None:
    source = Path("ml/stage7k5/worker.py").read_text(encoding="utf-8")
    assert "mlops.online_source_quarantine" in source
    assert "_quarantine_invalid_source(conn, message, exc)" in source
    assert "consumer.commit(message=message, asynchronous=False)" in source
    assert "config.max_processing_backoff_seconds" in source
    assert "--healthcheck" in source
    assert "STAGE_7K5_HEALTHCHECK_STATUS=PASS" in source


def test_stage7k5_compose_has_real_container_healthcheck() -> None:
    compose = Path("infra/docker/docker-compose.stage7k5.yml").read_text(encoding="utf-8")
    assert "healthcheck:" in compose
    assert '"--healthcheck"' in compose
    assert "PHARMSTOCK_STAGE7K5_HEARTBEAT_MAX_AGE_SECONDS" in compose
    assert "PHARMSTOCK_STAGE7K5_MAX_PENDING_OUTBOX_AGE_SECONDS" in compose
    assert "PHARMSTOCK_STAGE7K5_MAX_PROCESSING_BACKOFF_SECONDS" in compose
    assert "pharmstock-stage7k5-online:0.35.2" in compose


def test_stage7k5_runner_waits_for_docker_health_before_pass() -> None:
    source = Path("scripts/run_stage7k5.py").read_text(encoding="utf-8")
    assert "def _wait_container_health" in source
    assert '"pharmstock-stage7k-serving"' in source
    assert 'label="Stage 7K model-serving"' in source
    assert "Stage 7K serving readiness" in source
    assert '"pharmstock-stage7k5-online"' in source
    assert "STAGE_7K5_RELIABILITY_STATUS=PASS" in source
    assert source.index("Stage 7K serving readiness") < source.index(
        "Reconciling ML output topics + model metadata"
    )


def test_stage7k5_smoke_uses_unique_source_offsets() -> None:
    source = Path("ml/stage7k5/worker.py").read_text(encoding="utf-8")
    assert "smoke_offset = time.time_ns()" in source
    assert "stage7k5-smoke-{smoke_offset}-{os.getpid()}" in source
    assert "_insert_smoke_source(conn, source_id, smoke_offset, 2)" in source
    assert "'__stage7k5_smoke__', 0, 0" not in source


def test_write_heartbeat_closes_metrics_transaction(
    monkeypatch,
    tmp_path,
):
    from ml.stage7k5 import worker

    class FakeConn:
        def __init__(self):
            self.rollback_calls = 0
            self.commit_calls = 0

        def rollback(self):
            self.rollback_calls += 1

        def commit(self):
            self.commit_calls += 1

    conn = FakeConn()

    monkeypatch.setattr(
        worker,
        "ARTIFACT_ROOT",
        tmp_path,
    )

    monkeypatch.setattr(
        worker,
        "HEARTBEAT_PATH",
        tmp_path / "heartbeat.json",
    )

    monkeypatch.setattr(
        worker,
        "_operational_metrics",
        lambda _conn: {
            "pending_outbox": 0,
            "max_publish_attempts": 0,
            "oldest_pending_outbox_seconds": 0.0,
            "quarantine_rows": 0,
        },
    )

    stats = worker.WorkerStats()

    worker._write_heartbeat(
        stats,
        conn=conn,
    )

    assert conn.rollback_calls == 1
    assert conn.commit_calls == 0

    assert (
        tmp_path / "heartbeat.json"
    ).is_file()

