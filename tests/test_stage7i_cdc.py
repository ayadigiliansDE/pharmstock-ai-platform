from __future__ import annotations

from pharmstock.cdc import CDC_TOPICS
from pharmstock.cdc.stage7i import (
    Stage7IConfig,
    batch_id_for_offsets,
    capped_end_offsets,
    current_state_view_sql,
    normalize_resume_offsets,
    projected_storage_gib,
    storage_guard_status,
)
from scripts.run_checkpoint import checkpoint_command


def _offsets(value: int) -> dict[str, dict[str, int]]:
    return {item.topic: {"0": value, "1": value, "2": value} for item in CDC_TOPICS}


def test_capped_end_offsets_is_fair_and_bounded() -> None:
    start = _offsets(100)
    high = {
        topic: {partition: value + 1000 for partition, value in parts.items()}
        for topic, parts in start.items()
    }
    end = capped_end_offsets(start, high, 60)
    deltas = [
        end[topic][partition] - start[topic][partition]
        for topic in sorted(start)
        for partition in sorted(start[topic])
    ]
    assert sum(deltas) == 60
    assert min(deltas) > 0
    assert max(deltas) - min(deltas) <= 1


def test_batch_id_is_deterministic() -> None:
    start = _offsets(10)
    end = _offsets(11)
    assert batch_id_for_offsets(start, end) == batch_id_for_offsets(start, end)
    assert batch_id_for_offsets(start, end) != batch_id_for_offsets(_offsets(9), end)


def test_storage_guard_stops_before_hard_boundary() -> None:
    config = Stage7IConfig(
        project_id="p",
        raw_dataset="raw",
        delta_dataset="delta",
        current_dataset="current",
        location="EU",
        warn_gib=8.2,
        hard_stop_gib=8.5,
        max_batch_records=50_000,
        parquet_expansion_factor=6.0,
    )
    assert storage_guard_status(8.0, 8.1, config) == "SAFE"
    assert storage_guard_status(8.1, 8.3, config) == "WARN"
    assert storage_guard_status(8.1, 8.5, config) == "STOP"
    assert storage_guard_status(8.6, 8.6, config) == "STOP"


def test_projected_storage_is_conservative() -> None:
    current = 8 * 1024**3
    parquet = 50 * 1024**2
    projected = projected_storage_gib(current, parquet, 6.0)
    assert 8.29 < projected < 8.30


def test_current_state_view_overlays_without_rewriting_baseline() -> None:
    sql = current_state_view_sql(
        project_id="p",
        raw_dataset="raw",
        delta_dataset="delta",
        current_dataset="current",
        source_table="inventory.inventory_position",
        primary_key=("branch_id", "product_id"),
        fields=(
            ("branch_id", "STRING"),
            ("product_id", "STRING"),
            ("on_hand_units", "INT64"),
            ("updated_at", "TIMESTAMP"),
        ),
    )
    assert "CREATE OR REPLACE VIEW `p.current.inventory__inventory_position`" in sql
    assert "FROM `p.raw.inventory__inventory_position` AS b" in sql
    assert "FROM `p.delta.events`" in sql
    assert "l.op != 'd'" in sql
    assert "CAST(b.`branch_id` AS STRING)" in sql
    assert "CAST(b.`product_id` AS STRING)" in sql
    assert "ORDER BY COALESCE(source_lsn, -1) DESC, `partition` DESC, `offset` DESC" in sql
    assert "CREATE OR REPLACE TABLE" not in sql


def test_checkpoint_7i_routes_to_cdc_runner() -> None:
    command = checkpoint_command("7i")
    assert command[-1] == "scripts/run_stage7i_cdc.py"


def test_resume_offset_upgrade_adds_new_topic_from_low_watermark() -> None:
    low = _offsets(5)
    high = _offsets(9)
    new_topic = "pharmstock.ops.pos.demand_attempt"
    legacy = {topic: parts for topic, parts in _offsets(7).items() if topic != new_topic}
    normalized, added = normalize_resume_offsets(legacy, low, high)
    assert added == (new_topic,)
    assert normalized[new_topic] == {"0": 5, "1": 5, "2": 5}
    assert normalized["pharmstock.ops.pos.sale_header"] == {"0": 7, "1": 7, "2": 7}
