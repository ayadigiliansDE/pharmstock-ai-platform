from __future__ import annotations

from pathlib import Path

import pytest

from pharmstock.cdc import CDC_TOPICS
from pharmstock.onprem import CDC_TABLES
from pharmstock.rebuild import (
    BIGQUERY_REBUILD_DATASET,
    CORE_ACCEPTANCE_MINIMUMS,
    POSTGRES_JDBC_PACKAGE,
    SNAPSHOT_TABLES,
    SPARK_KAFKA_PACKAGE,
    SPARK_VERSION,
    rebuild_contract,
    spark_offsets_json,
    validate_offset_range,
)
from scripts.run_checkpoint import checkpoint_command

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/run_stage7g_rebuild.py"
SNAPSHOT_JOB = ROOT / "spark/jobs/stage7g_snapshot.py"
CDC_JOB = ROOT / "spark/jobs/stage7g_cdc_catchup.py"
COMPOSE = ROOT / "infra/docker/docker-compose.stage7g.yml"
DOC = ROOT / "docs/STAGE_07G_LARGE_SCALE_REBUILD.md"


def _offsets(base: int) -> dict[str, dict[str, int]]:
    return {
        item.topic: {str(partition): base for partition in range(item.partitions)}
        for item in CDC_TOPICS
    }


def test_stage7g_pins_current_spark_and_secure_postgres_jdbc() -> None:
    assert SPARK_VERSION == "4.2.0"
    assert SPARK_KAFKA_PACKAGE == "org.apache.spark:spark-sql-kafka-0-10_2.13:4.2.0"
    assert POSTGRES_JDBC_PACKAGE == "org.postgresql:postgresql:42.7.13"


def test_stage7g_snapshots_complete_production_like_scope() -> None:
    names = {spec.source_table for spec in SNAPSHOT_TABLES}
    assert len(SNAPSHOT_TABLES) == 26
    assert set(CDC_TABLES).issubset(names)
    assert {
        "master.product",
        "master.product_price_history",
        "master.pharmacy_branch",
        "commercial.product_unit_economics",
        "customer.customer_profile",
        "customer.patient_profile",
        "pos.prescription_context",
        "pos.demand_attempt",
    }.issubset(names)


def test_stage7g_marks_exactly_stage7f_tables_as_cdc_managed() -> None:
    managed = {spec.source_table for spec in SNAPSHOT_TABLES if spec.cdc_managed}
    assert managed == set(CDC_TABLES)


def test_stage7g_offset_range_is_deterministic_and_gap_safe() -> None:
    start = _offsets(10)
    end = _offsets(12)
    assert validate_offset_range(start, end) == len(CDC_TOPICS) * 3 * 2
    encoded = spark_offsets_json(start)
    assert encoded.startswith("{")
    assert "pharmstock.ops.pos.sale_header" in encoded


def test_stage7g_rejects_backward_offsets() -> None:
    start = _offsets(10)
    end = _offsets(10)
    first_topic = CDC_TOPICS[0].topic
    end[first_topic]["0"] = 9
    with pytest.raises(ValueError, match="moved backwards"):
        validate_offset_range(start, end)


def test_stage7g_contract_never_replays_history_through_kafka() -> None:
    contract = rebuild_contract()
    assert contract["cutover"]["historical_rows_replayed_via_kafka"] is False
    assert contract["cutover"]["start_offsets_captured_before_snapshot"] is True
    assert contract["cutover"]["end_offsets_captured_after_snapshot"] is True
    assert contract["bigquery"]["cloud_mutation_in_checkpoint"] is False
    assert contract["bigquery"]["dataset"] == BIGQUERY_REBUILD_DATASET


def test_stage7g_acceptance_keeps_million_scale_thresholds() -> None:
    assert CORE_ACCEPTANCE_MINIMUMS["master.pharmacy_branch"] == 5_000
    assert CORE_ACCEPTANCE_MINIMUMS["pos.sale_header"] == 1_200_000
    assert CORE_ACCEPTANCE_MINIMUMS["pos.sale_line"] == 2_000_000
    assert CORE_ACCEPTANCE_MINIMUMS["customer.customer_profile"] == 250_000


def test_stage7g_runner_captures_offsets_around_snapshot_and_persists_resume_point() -> None:
    text = RUNNER.read_text(encoding="utf-8")
    first_capture = text.index('"cutover_start_offsets.json"')
    snapshot_run = text.index('_spark_submit("stage7g_snapshot.py")')
    second_capture = text.index('"cutover_end_offsets.json"')
    assert first_capture < snapshot_run < second_capture
    assert '"cdc_resume_offsets.json"' in text
    assert 'STAGE_7G_STATUS=PASS' in text


def test_stage7g_spark_snapshot_uses_parallel_jdbc_and_snappy_parquet() -> None:
    text = SNAPSHOT_JOB.read_text(encoding="utf-8")
    assert '.format("jdbc")' in text
    assert 'hashtextextended' in text
    assert 'partitionColumn' in text
    assert 'compression", "snappy"' in text


def test_stage7g_cdc_job_reads_exact_range_and_reconciles_changed_tables() -> None:
    text = CDC_JOB.read_text(encoding="utf-8")
    assert 'option("startingOffsets"' in text
    assert 'option("endingOffsets"' in text
    assert 'left_anti' in text
    assert 'unionByName' in text
    assert 'reconciled_tables' in text


def test_stage7g_compose_connects_spark_to_postgres_and_kafka() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    assert "apache/spark:4.2.0-python3" in text
    assert "jdbc:postgresql://postgres:5432/pharmstock_ops" in text
    assert "kafka:19092" in text
    assert "PHARMSTOCK_APP_PASSWORD" in text


def test_stage7g_docs_explain_controlled_rebuild_and_no_cloud_mutation() -> None:
    text = DOC.read_text(encoding="utf-8")
    assert "[start_offset,end_offset)" in text
    assert "does not go through Kafka" in text
    assert "no cloud mutation" in text.lower()
    assert "42.7.13" in text


def test_checkpoint_launcher_knows_stage7g() -> None:
    command = checkpoint_command("7g")
    assert command[-1] == "scripts/run_stage7g_rebuild.py"


def test_stage7g_memory_safe_runtime_profile() -> None:
    runner = RUNNER.read_text(encoding="utf-8")
    snapshot = SNAPSHOT_JOB.read_text(encoding="utf-8")
    assert '"local[2]"' in runner
    assert '"--driver-memory"' in runner
    assert '"2g"' in runner
    assert 'spark.default.parallelism=4' in runner
    assert 'spark.sql.shuffle.partitions=4' in runner
    assert '.option("fetchsize", "5000")' in snapshot
    assert 'spark.hadoop.parquet.block.size", "67108864"' in snapshot
    assert 'spark.sql.files.maxRecordsPerFile", "250000"' in snapshot
