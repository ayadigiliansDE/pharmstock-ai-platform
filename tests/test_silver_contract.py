import ast
import json
from pathlib import Path

import pytest

from pharmstock.analytics import (
    SILVER_TABLE_BY_EVENT,
    semantic_event_hash,
    silver_table_for_event_type,
    validate_silver_event,
)

EVENT_ID = "50000000-0000-4000-8000-000000000001"
AGGREGATE_ID = "50000000-0000-4000-8000-000000000002"
CORRELATION_ID = "50000000-0000-4000-8000-000000000003"
DEMAND_ID = "50000000-0000-4000-8000-000000000004"
BASKET_ID = "50000000-0000-4000-8000-000000000005"
BRANCH_ID = "50000000-0000-4000-8000-000000000006"
PRODUCT_ID = "50000000-0000-4000-8000-000000000007"


def _sale_event(**payload_overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "demand_id": DEMAND_ID,
        "basket_id": BASKET_ID,
        "branch_id": BRANCH_ID,
        "product_id": PRODUCT_ID,
        "channel": "in_store",
        "requested_quantity": 2,
        "fulfilled_quantity": 2,
        "lost_quantity": 0,
        "fulfillment_status": "fulfilled",
        "pricing_status": "not_simulated",
    }
    payload.update(payload_overrides)
    return {
        "event_id": EVENT_ID,
        "event_type": "sale.units_fulfilled",
        "schema_version": "1.0",
        "aggregate_type": "demand_line",
        "aggregate_id": AGGREGATE_ID,
        "occurred_at": "2026-08-22T18:00:00+00:00",
        "recorded_at": "2026-08-22T18:00:01+00:00",
        "correlation_id": CORRELATION_ID,
        "causation_id": None,
        "payload": payload,
    }


def test_silver_mapping_covers_all_stage4b_event_types() -> None:
    assert SILVER_TABLE_BY_EVENT == {
        "sale.units_fulfilled": "sales_units_fulfilled",
        "inventory.quantity_changed": "inventory_quantity_changed",
        "inventory.reorder_required": "inventory_reorder_required",
        "purchase_order.created": "purchase_order_created",
        "goods_receipt.received": "goods_receipt_received",
        "restock.applied": "restock_applied",
    }


def test_valid_sale_event_passes_event_specific_silver_validation() -> None:
    result = validate_silver_event(json.dumps(_sale_event()))

    assert result.is_valid is True
    assert result.error is None
    assert result.event_id == EVENT_ID
    assert result.silver_table == "sales_units_fulfilled"


def test_invalid_sale_quantity_math_is_rejected() -> None:
    result = validate_silver_event(
        json.dumps(_sale_event(requested_quantity=2, fulfilled_quantity=5, lost_quantity=0))
    )

    assert result.is_valid is False
    assert "schema validation" in (result.error or "")


def test_semantic_hash_ignores_recorded_at_replay_observation_time() -> None:
    first = _sale_event()
    second = _sale_event()
    second["recorded_at"] = "2026-08-23T09:30:00+00:00"

    assert semantic_event_hash(json.dumps(first)) == semantic_event_hash(json.dumps(second))


def test_semantic_hash_detects_payload_change_for_same_event_id() -> None:
    first = _sale_event()
    second = _sale_event(channel="delivery")

    assert semantic_event_hash(json.dumps(first)) != semantic_event_hash(json.dumps(second))


def test_unknown_silver_event_type_has_no_table() -> None:
    with pytest.raises(ValueError, match="unknown Stage 4B event_type"):
        silver_table_for_event_type("unknown.event")


def test_stage4b_spark_job_is_python_310_compatible() -> None:
    source = Path("spark/jobs/stage4b_silver.py").read_text(encoding="utf-8")
    ast.parse(source, filename="stage4b_silver.py", feature_version=(3, 10))
    assert "from datetime import UTC" not in source
    assert "datetime.now(timezone.utc)" in source


def test_stage4b_spark_job_uses_event_id_and_semantic_hash_for_deduplication() -> None:
    source = Path("spark/jobs/stage4b_silver.py").read_text(encoding="utf-8")

    assert 'Window.partitionBy("event.event_id")' in source
    assert 'F.countDistinct("semantic_event_sha256")' in source
    assert 'semantic_hash_excludes": ["recorded_at"]' in source


def test_stage4b_has_six_event_specific_payload_schemas() -> None:
    source = Path("spark/jobs/stage4b_silver.py").read_text(encoding="utf-8")

    for schema_name in (
        "SALE_SCHEMA",
        "INVENTORY_SCHEMA",
        "REORDER_SCHEMA",
        "PURCHASE_ORDER_SCHEMA",
        "RECEIPT_SCHEMA",
        "RESTOCK_SCHEMA",
    ):
        assert schema_name in source


def test_stage4b_checkpoint_exercises_duplicates_conflicts_and_payload_rejects() -> None:
    source = Path("scripts/run_stage4b_checkpoint.py").read_text(encoding="utf-8")

    assert "replay copies" in source
    assert "event-id conflict" in source
    assert "payload-invalid envelope" in source
    assert "STAGE_4B_STATUS=PASS" in source


def test_spark_analytics_import_path_does_not_require_application_site_packages() -> None:
    import subprocess
    import sys

    code = (
        "import sys; sys.path.insert(0, 'src'); "
        "from pharmstock.analytics.bronze import BRONZE_TOPICS; "
        "from pharmstock.analytics.silver_contracts import SILVER_TABLE_BY_EVENT; "
        "assert len(BRONZE_TOPICS) == 3; assert len(SILVER_TABLE_BY_EVENT) == 6"
    )
    completed = subprocess.run(
        [sys.executable, "-S", "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_stage4b_spark_job_uses_dependency_light_silver_contracts() -> None:
    source = Path("spark/jobs/stage4b_silver.py").read_text(encoding="utf-8")
    package_source = Path("src/pharmstock/analytics/__init__.py").read_text(encoding="utf-8")

    assert "from pharmstock.analytics.silver_contracts import SILVER_TABLE_BY_EVENT" in source
    assert "from pharmstock.analytics.silver import" not in package_source
