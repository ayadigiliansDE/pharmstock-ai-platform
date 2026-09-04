from __future__ import annotations

from http.client import RemoteDisconnected
from pathlib import Path

import pytest

from pharmstock.cdc import (
    CDC_TOPICS,
    CONNECTOR_NAME,
    DEBEZIUM_IMAGE,
    DEBEZIUM_RELEASE,
    SNAPSHOT_MODE,
    cdc_contract,
    connector_config,
    redacted_connector_config,
    topic_name,
)
from pharmstock.onprem import (
    CDC_PLUGIN,
    CDC_PUBLICATION,
    CDC_SLOT,
    CDC_TABLES,
    DEBEZIUM_COMPATIBLE_RELEASE,
)
from scripts.run_checkpoint import checkpoint_command
from scripts.run_stage7f_cdc import (
    Stage7FExecutionError,
    _http_json,
    _unwrap_connect_json,
)

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "infra/docker/docker-compose.stage7f.yml"
RUNNER = ROOT / "scripts/run_stage7f_cdc.py"
DOC = ROOT / "docs/STAGE_07F_CDC_KAFKA.md"


def test_stage7f_pins_debezium_to_compatible_series() -> None:
    assert DEBEZIUM_RELEASE == DEBEZIUM_COMPATIBLE_RELEASE == "3.6.1.Final"
    assert DEBEZIUM_IMAGE == "quay.io/debezium/connect:3.6"


def test_stage7f_compose_adds_connect_without_replacing_source_or_broker() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    assert "quay.io/debezium/connect:3.6" in text
    assert 'BOOTSTRAP_SERVERS: "kafka:19092"' in text
    assert "condition: service_healthy" in text
    assert "postgres:" in text
    assert "kafka:" in text


def test_connector_uses_precreated_pgoutput_publication_and_canonical_slot() -> None:
    config = connector_config("secret")
    assert config["plugin.name"] == CDC_PLUGIN == "pgoutput"
    assert config["publication.name"] == CDC_PUBLICATION
    assert config["publication.autocreate.mode"] == "disabled"
    assert config["slot.name"] == CDC_SLOT
    assert config["table.include.list"] == ",".join(CDC_TABLES)


def test_stage7f_does_not_snapshot_million_scale_history() -> None:
    config = connector_config("secret")
    contract = cdc_contract()
    assert SNAPSHOT_MODE == "no_data"
    assert config["snapshot.mode"] == "no_data"
    assert contract["snapshot_boundary"]["historical_stage7e_rows_republished"] is False
    assert "Stage 7G" in contract["snapshot_boundary"]["reason"]


def test_stage7f_has_one_table_specific_topic_per_cdc_table() -> None:
    assert len(CDC_TOPICS) == len(CDC_TABLES) == 14
    assert [item.table for item in CDC_TOPICS] == list(CDC_TABLES)
    assert all(item.partitions == 3 for item in CDC_TOPICS)
    assert topic_name("pos.sale_header") == "pharmstock.ops.pos.sale_header"
    assert topic_name("procurement.supplier") == "pharmstock.ops.procurement.supplier"
    assert topic_name("pos.demand_attempt") == "pharmstock.ops.pos.demand_attempt"


def test_connector_artifact_redacts_password() -> None:
    config = redacted_connector_config("do-not-persist-me")
    assert config["database.password"] == "<REDACTED>"
    assert "do-not-persist-me" not in str(config)


def test_stage7f_runner_requires_stage7e_and_uses_isolated_probe() -> None:
    text = RUNNER.read_text(encoding="utf-8")
    assert "artifacts/stage7e/_SUCCESS" in text
    assert "Stage 7F CDC Probe" in text
    assert "INSERT INTO procurement.supplier" in text
    assert "UPDATE procurement.supplier" in text
    assert "DELETE FROM procurement.supplier" in text
    assert '["c", "u", "d"]' in text


def test_stage7f_runner_never_persists_cdc_secret() -> None:
    text = RUNNER.read_text(encoding="utf-8")
    assert "connector_config_redacted.json" in text
    assert "redacted_connector_config" in text
    assert "database.password" not in text


def test_stage7f_docs_explain_rebuild_boundary() -> None:
    text = DOC.read_text(encoding="utf-8")
    assert "snapshot.mode=no_data" in text
    assert "Stage 7G" in text
    assert "c -> u -> d" in text


def test_checkpoint_launcher_knows_stage7f() -> None:
    command = checkpoint_command("7f")
    assert command[-1] == "scripts/run_stage7f_cdc.py"
    assert CONNECTOR_NAME == "pharmstock-postgres-cdc"


def test_stage7f_retries_transient_remote_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    def _disconnect(*_args: object, **_kwargs: object) -> None:
        raise RemoteDisconnected("Remote end closed connection without response")

    monkeypatch.setattr("scripts.run_stage7f_cdc.request.urlopen", _disconnect)
    with pytest.raises(Stage7FExecutionError, match="Kafka Connect REST unavailable"):
        _http_json("GET", "/connector-plugins")


def test_stage7f_probe_pins_assigned_partitions_to_high_watermark() -> None:
    text = RUNNER.read_text(encoding="utf-8")
    assert "get_watermark_offsets" in text
    assert "consumer.seek" in text
    assert "before touching PostgreSQL" in text


def test_stage7f_unwraps_kafka_connect_schema_payload_envelope() -> None:
    wrapped_value = {
        "schema": {"type": "struct"},
        "payload": {
            "before": None,
            "after": {"supplier_id": "probe-id"},
            "source": {"schema": "procurement", "table": "supplier"},
            "op": "c",
        },
    }
    wrapped_key = {
        "schema": {"type": "struct"},
        "payload": {"supplier_id": "probe-id"},
    }

    assert _unwrap_connect_json(wrapped_value)["op"] == "c"
    assert _unwrap_connect_json(wrapped_value)["after"]["supplier_id"] == "probe-id"
    assert _unwrap_connect_json(wrapped_key)["supplier_id"] == "probe-id"
    assert _unwrap_connect_json({"op": "u"}) == {"op": "u"}


def test_stage7f_extends_publication_with_live_demand_signal() -> None:
    runner = RUNNER.read_text(encoding="utf-8")
    support_sql = (ROOT / "infra/docker/postgres/sql/005_stage7e_support.sql").read_text(
        encoding="utf-8"
    )
    assert "_ensure_publication_tables" in runner
    assert "ALTER PUBLICATION" in runner
    assert "ADD TABLE pos.demand_attempt" in support_sql
