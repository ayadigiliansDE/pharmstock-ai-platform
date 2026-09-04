"""Stage 7K.5 CDC-triggered online feature assembly and champion inference worker."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error, request

from pharmstock.ml.stage7k5 import (
    DEFAULT_HEARTBEAT_MAX_AGE_SECONDS,
    DEFAULT_MAX_PENDING_OUTBOX,
    DEFAULT_MAX_PENDING_OUTBOX_AGE_SECONDS,
    DEMAND_FORECAST_TOPIC,
    EXPIRY_ALERT_TOPIC,
    ML_OUTPUT_TOPICS,
    MONITORED_CDC_TOPICS,
    REORDER_RECOMMENDATION_TOPIC,
    STOCKOUT_PREDICTION_TOPIC,
    CdcChange,
    alert_is_actionable,
    config_from_environment,
    decode_debezium_change,
    numeric,
    prediction_event_id,
    source_event_id,
    stockout_severity,
)

ARTIFACT_ROOT = Path(os.getenv("PHARMSTOCK_STAGE7K5_ARTIFACT_ROOT", "artifacts/stage7k5"))
HEARTBEAT_PATH = ARTIFACT_ROOT / "worker_heartbeat.json"
SMOKE_REPORT_PATH = ARTIFACT_ROOT / "smoke_report.json"

DEMAND_FEATURE_SQL = r"""
WITH as_of AS (
    SELECT COALESCE(MAX(transaction_ts::date), CURRENT_DATE) AS as_of_date
    FROM pos.demand_attempt
), calendar AS (
    SELECT generate_series(a.as_of_date - 28, a.as_of_date, interval '1 day')::date AS business_date
    FROM as_of a
), demand_daily AS (
    SELECT
        transaction_ts::date AS business_date,
        SUM(requested_units)::double precision AS requested_units,
        SUM(fulfilled_units)::double precision AS fulfilled_units,
        SUM(lost_units)::double precision AS lost_units,
        COUNT(*) FILTER (WHERE outcome = 'OUT_OF_STOCK')::double precision AS stockout_attempts
    FROM pos.demand_attempt
    CROSS JOIN as_of a
    WHERE product_id = %s::uuid
      AND transaction_ts::date BETWEEN a.as_of_date - 28 AND a.as_of_date
    GROUP BY 1
), sales_daily AS (
    SELECT
        h.transaction_ts::date AS business_date,
        COUNT(DISTINCT h.branch_id)::double precision AS selling_branches,
        COUNT(DISTINCT h.sale_id)::double precision AS sales_transactions,
        SUM(l.quantity)::double precision AS units_sold,
        SUM(l.net_sales_egp)::double precision AS net_sales_egp,
        SUM(l.gross_profit_egp)::double precision AS gross_profit_egp
    FROM pos.sale_header h
    JOIN pos.sale_line l USING (sale_id)
    CROSS JOIN as_of a
    WHERE l.product_id = %s::uuid
      AND h.transaction_status = 'COMPLETED'
      AND h.transaction_ts::date BETWEEN a.as_of_date - 28 AND a.as_of_date
    GROUP BY 1
), series AS (
    SELECT
        c.business_date,
        COALESCE(d.requested_units, 0.0) AS requested_units,
        COALESCE(d.fulfilled_units, 0.0) AS fulfilled_units,
        COALESCE(d.lost_units, 0.0) AS lost_units,
        COALESCE(d.stockout_attempts, 0.0) AS stockout_attempts,
        COALESCE(s.selling_branches, 0.0) AS selling_branches,
        COALESCE(s.sales_transactions, 0.0) AS sales_transactions,
        COALESCE(s.units_sold, 0.0) AS units_sold,
        COALESCE(s.net_sales_egp, 0.0) AS net_sales_egp,
        COALESCE(s.gross_profit_egp, 0.0) AS gross_profit_egp
    FROM calendar c
    LEFT JOIN demand_daily d USING (business_date)
    LEFT JOIN sales_daily s USING (business_date)
), features AS (
    SELECT
        *,
        LAG(requested_units, 1) OVER (ORDER BY business_date) AS requested_lag_1,
        LAG(requested_units, 7) OVER (ORDER BY business_date) AS requested_lag_7,
        LAG(requested_units, 14) OVER (ORDER BY business_date) AS requested_lag_14,
        LAG(requested_units, 28) OVER (ORDER BY business_date) AS requested_lag_28,
        AVG(requested_units) OVER (
            ORDER BY business_date ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING
        ) AS requested_avg_7,
        AVG(requested_units) OVER (
            ORDER BY business_date ROWS BETWEEN 28 PRECEDING AND 1 PRECEDING
        ) AS requested_avg_28,
        STDDEV_SAMP(requested_units) OVER (
            ORDER BY business_date ROWS BETWEEN 28 PRECEDING AND 1 PRECEDING
        ) AS requested_stddev_28,
        AVG(stockout_attempts) OVER (
            ORDER BY business_date ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING
        ) AS stockout_avg_7
    FROM series
)
SELECT
    p.retail_price_egp::double precision AS retail_price_egp,
    f.selling_branches,
    f.sales_transactions,
    f.units_sold,
    f.requested_units,
    f.fulfilled_units,
    f.lost_units,
    CASE WHEN f.requested_units > 0 THEN f.fulfilled_units / f.requested_units ELSE 1.0 END
        AS fill_rate,
    f.stockout_attempts,
    f.net_sales_egp,
    f.gross_profit_egp,
    (EXTRACT(DOW FROM f.business_date)::integer + 1)::double precision AS day_of_week,
    EXTRACT(MONTH FROM f.business_date)::double precision AS month_of_year,
    CASE WHEN f.requested_units > 0 THEN f.lost_units / f.requested_units ELSE 0.0 END
        AS lost_rate,
    COALESCE(f.requested_lag_1, 0.0) AS requested_lag_1,
    COALESCE(f.requested_lag_7, 0.0) AS requested_lag_7,
    COALESCE(f.requested_lag_14, 0.0) AS requested_lag_14,
    COALESCE(f.requested_lag_28, 0.0) AS requested_lag_28,
    COALESCE(f.requested_avg_7, 0.0) AS requested_avg_7,
    COALESCE(f.requested_avg_28, 0.0) AS requested_avg_28,
    COALESCE(f.requested_stddev_28, 0.0) AS requested_stddev_28,
    COALESCE(f.stockout_avg_7, 0.0) AS stockout_avg_7,
    COALESCE(f.requested_avg_7, 0.0) / GREATEST(COALESCE(f.requested_avg_28, 0.0), 1.0)
        AS demand_trend_7_28,
    f.business_date AS feature_as_of_date
FROM features f
JOIN as_of a ON f.business_date = a.as_of_date
JOIN master.product p ON p.product_id = %s::uuid
"""

BRANCH_PRODUCT_FEATURE_SQL = r"""
WITH as_of AS (
    SELECT COALESCE(MAX(transaction_ts::date), CURRENT_DATE) AS as_of_date
    FROM pos.demand_attempt
), daily AS (
    SELECT
        transaction_ts::date AS business_date,
        SUM(requested_units)::double precision AS requested_units,
        SUM(fulfilled_units)::double precision AS fulfilled_units,
        SUM(lost_units)::double precision AS lost_units,
        MAX(CASE WHEN outcome = 'OUT_OF_STOCK' THEN 1 ELSE 0 END)::double precision
            AS stockout_today
    FROM pos.demand_attempt
    CROSS JOIN as_of a
    WHERE branch_id = %s::uuid
      AND product_id = %s::uuid
      AND transaction_ts::date BETWEEN a.as_of_date - 35 AND a.as_of_date
    GROUP BY 1
), stockout_stats AS (
    SELECT
        AVG(requested_units) FILTER (WHERE business_date >= a.as_of_date - 7
                                      AND business_date < a.as_of_date) AS requested_avg_7,
        AVG(requested_units) FILTER (WHERE business_date >= a.as_of_date - 28
                                      AND business_date < a.as_of_date) AS requested_avg_28,
        STDDEV_SAMP(requested_units) FILTER (WHERE business_date >= a.as_of_date - 28
                                             AND business_date < a.as_of_date)
            AS requested_stddev_28,
        SUM(lost_units) FILTER (WHERE business_date >= a.as_of_date - 28
                                AND business_date < a.as_of_date)
            / GREATEST(
                SUM(requested_units) FILTER (WHERE business_date >= a.as_of_date - 28
                                             AND business_date < a.as_of_date),
                1.0
            ) AS lost_rate_28,
        AVG(stockout_today) FILTER (WHERE business_date >= a.as_of_date - 28
                                    AND business_date < a.as_of_date) AS stockout_rate_28
    FROM daily
    CROSS JOIN as_of a
), policy_stats AS (
    SELECT
        AVG(requested_units) AS avg_daily_requested_units,
        STDDEV_SAMP(requested_units) AS demand_stddev_units,
        AVG(fulfilled_units) AS avg_daily_units_sold
    FROM daily
), latest_supplier AS (
    SELECT s.nominal_lead_time_days, s.reliability_score
    FROM procurement.purchase_order po
    JOIN procurement.supplier s USING (supplier_id)
    WHERE po.branch_id = %s::uuid
    ORDER BY po.ordered_at DESC
    LIMIT 1
), inbound AS (
    SELECT COALESCE(SUM(pol.ordered_units), 0)::double precision AS inbound_units
    FROM procurement.purchase_order po
    JOIN procurement.purchase_order_line pol USING (purchase_order_id)
    WHERE po.branch_id = %s::uuid
      AND pol.product_id = %s::uuid
      AND UPPER(COALESCE(po.status, '')) NOT IN ('RECEIVED', 'CANCELLED', 'CLOSED')
)
SELECT
    COALESCE(i.available_units, 0)::double precision AS available_units,
    COALESCE(s.requested_avg_7, 0.0)::double precision AS requested_avg_7,
    COALESCE(s.requested_avg_28, 0.0)::double precision AS requested_avg_28,
    COALESCE(s.requested_stddev_28, 0.0)::double precision AS requested_stddev_28,
    COALESCE(s.lost_rate_28, 0.0)::double precision AS lost_rate_28,
    COALESCE(s.stockout_rate_28, 0.0)::double precision AS stockout_rate_28,
    COALESCE(ls.nominal_lead_time_days, 3)::double precision AS supplier_lead_time_days,
    COALESCE(ls.reliability_score, 0.90)::double precision AS supplier_reliability,
    (EXTRACT(DOW FROM a.as_of_date)::integer + 1)::double precision AS day_of_week,
    EXTRACT(MONTH FROM a.as_of_date)::double precision AS month_of_year,
    COALESCE(p.avg_daily_requested_units, 0.0)::double precision AS avg_daily_requested_units,
    COALESCE(p.demand_stddev_units, 0.0)::double precision AS demand_stddev_units,
    COALESCE(p.avg_daily_units_sold, 0.0)::double precision AS avg_daily_units_sold,
    COALESCE(ib.inbound_units, 0.0)::double precision AS inbound_units,
    a.as_of_date AS feature_as_of_date
FROM as_of a
CROSS JOIN stockout_stats s
CROSS JOIN policy_stats p
CROSS JOIN inbound ib
LEFT JOIN latest_supplier ls ON true
LEFT JOIN inventory.inventory_position i
  ON i.branch_id = %s::uuid AND i.product_id = %s::uuid
"""

EXPIRY_FEATURE_SQL = r"""
WITH as_of AS (
    SELECT COALESCE(MAX(transaction_ts::date), CURRENT_DATE) AS as_of_date
    FROM pos.demand_attempt
), daily AS (
    SELECT
        transaction_ts::date AS business_date,
        SUM(fulfilled_units)::double precision AS units_sold,
        SUM(requested_units)::double precision AS requested_units
    FROM pos.demand_attempt
    CROSS JOIN as_of a
    WHERE branch_id = %s::uuid
      AND product_id = %s::uuid
      AND transaction_ts::date BETWEEN a.as_of_date - 35 AND a.as_of_date
    GROUP BY 1
), recent AS (
    SELECT
        AVG(units_sold) AS avg_daily_units_sold,
        STDDEV_SAMP(requested_units) AS demand_stddev_units
    FROM daily
)
SELECT
    b.batch_id::text AS batch_id,
    b.branch_id::text AS branch_id,
    b.product_id::text AS product_id,
    (b.expiry_date - a.as_of_date)::integer AS days_to_expiry,
    b.quantity_on_hand::integer AS quantity_on_hand,
    COALESCE(r.avg_daily_units_sold, 0.0)::double precision AS avg_daily_units_sold,
    COALESCE(r.demand_stddev_units, 0.0)::double precision AS demand_stddev_units,
    a.as_of_date AS feature_as_of_date
FROM inventory.stock_batch b
CROSS JOIN as_of a
CROSS JOIN recent r
WHERE b.branch_id = %s::uuid
  AND b.product_id = %s::uuid
  AND b.quantity_on_hand > 0
  AND UPPER(COALESCE(b.status, 'ACTIVE')) = 'ACTIVE'
ORDER BY b.expiry_date, b.received_at
LIMIT %s
"""


@dataclass(slots=True)
class WorkerStats:
    processed_events: int = 0
    duplicate_events: int = 0
    quarantined_events: int = 0
    emitted_predictions: int = 0
    published_outbox: int = 0
    retry_attempt: int = 0
    last_error: str | None = None
    last_source_event_id: str | None = None


class Stage7K5RuntimeError(RuntimeError):
    pass


def _pg_connect():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ModuleNotFoundError as exc:
        raise Stage7K5RuntimeError("psycopg is required by the Stage 7K.5 worker") from exc
    return psycopg.connect(
        host=os.getenv("PHARMSTOCK_POSTGRES_HOST", "postgres"),
        port=int(os.getenv("PHARMSTOCK_POSTGRES_INTERNAL_PORT", "5432")),
        dbname=os.getenv("PHARMSTOCK_POSTGRES_DB", "pharmstock_ops"),
        user=os.getenv("PHARMSTOCK_POSTGRES_USER", "pharmstock_admin"),
        password=os.getenv("PHARMSTOCK_POSTGRES_PASSWORD", "pharmstock_local_dev_admin"),
        row_factory=dict_row,
        autocommit=False,
    )


def _jsonb(value: dict[str, Any]):
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def _http_json(method: str, url: str, payload: dict[str, Any] | None = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=15) as response:
            raw = response.read()
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise Stage7K5RuntimeError(f"model API HTTP {exc.code}: {body}") from exc
    except (error.URLError, OSError) as exc:
        raise Stage7K5RuntimeError(f"model API unavailable: {exc}") from exc
    return None if not raw else json.loads(raw.decode("utf-8"))


def _model_metadata(model_api_uri: str) -> dict[str, dict[str, Any]]:
    health = _http_json("GET", f"{model_api_uri}/health")
    if health.get("status") != "healthy" or int(health.get("production_ready_models", 0)) != 4:
        raise Stage7K5RuntimeError(f"Stage 7K serving is not fully healthy: {health}")
    response = _http_json("GET", f"{model_api_uri}/models")
    models = {str(item["key"]): item for item in response.get("models", [])}
    required = {
        "demand_forecast",
        "stockout_risk",
        "reorder_recommendation",
        "expiry_slow_moving_risk",
    }
    if set(models) != required or not all(
        bool(models[key].get("production_ready")) for key in required
    ):
        raise Stage7K5RuntimeError("all four Stage 7K champions must be production-ready")
    return models


def _predict(model_api_uri: str, model_key: str, features: dict[str, float]) -> dict[str, Any]:
    return _http_json(
        "POST",
        f"{model_api_uri}/predict/{model_key}",
        {"records": [features]},
    )


def _ensure_output_topics(bootstrap_servers: str) -> tuple[str, ...]:
    try:
        from confluent_kafka.admin import AdminClient, NewTopic
    except ModuleNotFoundError as exc:
        raise Stage7K5RuntimeError("confluent-kafka is required by Stage 7K.5") from exc
    admin = AdminClient({"bootstrap.servers": bootstrap_servers, "client.id": "stage7k5-admin"})
    existing = set(admin.list_topics(timeout=10).topics)
    missing = [item for item in ML_OUTPUT_TOPICS if item.name not in existing]
    if missing:
        futures = admin.create_topics(
            [
                NewTopic(
                    item.name,
                    num_partitions=item.partitions,
                    replication_factor=item.replication_factor,
                    config=item.config,
                )
                for item in missing
            ]
        )
        for name, future in futures.items():
            try:
                future.result(timeout=15)
            except Exception as exc:
                refreshed = set(admin.list_topics(timeout=10).topics)
                if name not in refreshed:
                    raise Stage7K5RuntimeError(f"failed to create ML output topic {name}") from exc
    refreshed = set(admin.list_topics(timeout=10).topics)
    absent = [item.name for item in ML_OUTPUT_TOPICS if item.name not in refreshed]
    if absent:
        raise Stage7K5RuntimeError(f"ML output topics missing: {absent}")
    return tuple(item.name for item in ML_OUTPUT_TOPICS)


def _producer(bootstrap_servers: str):
    from confluent_kafka import Producer

    return Producer(
        {
            "bootstrap.servers": bootstrap_servers,
            "client.id": "pharmstock-stage7k5-producer",
            "enable.idempotence": True,
            "acks": "all",
            "compression.type": "zstd",
        }
    )


def _consumer(bootstrap_servers: str, group_id: str):
    from confluent_kafka import Consumer

    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap_servers,
            "client.id": "pharmstock-stage7k5-consumer",
            "group.id": group_id,
            "auto.offset.reset": "latest",
            "enable.auto.commit": False,
            "isolation.level": "read_committed",
        }
    )
    consumer.subscribe(list(MONITORED_CDC_TOPICS))
    return consumer


def _finite_feature_dict(row: dict[str, Any], keys: list[str]) -> dict[str, float]:
    return {key: numeric(row.get(key), 0.0) for key in keys}


def _demand_features(conn, product_id: str) -> tuple[dict[str, float], str]:
    keys = [
        "retail_price_egp",
        "selling_branches",
        "sales_transactions",
        "units_sold",
        "requested_units",
        "fulfilled_units",
        "lost_units",
        "fill_rate",
        "stockout_attempts",
        "net_sales_egp",
        "gross_profit_egp",
        "day_of_week",
        "month_of_year",
        "lost_rate",
        "requested_lag_1",
        "requested_lag_7",
        "requested_lag_14",
        "requested_lag_28",
        "requested_avg_7",
        "requested_avg_28",
        "requested_stddev_28",
        "stockout_avg_7",
        "demand_trend_7_28",
    ]
    row = conn.execute(DEMAND_FEATURE_SQL, (product_id, product_id, product_id)).fetchone()
    if not row:
        raise Stage7K5RuntimeError(f"cannot assemble demand features for product {product_id}")
    return _finite_feature_dict(row, keys), str(row["feature_as_of_date"])


def _branch_product_features(conn, branch_id: str, product_id: str) -> tuple[dict[str, Any], str]:
    params = (branch_id, product_id, branch_id, branch_id, product_id, branch_id, product_id)
    row = conn.execute(BRANCH_PRODUCT_FEATURE_SQL, params).fetchone()
    if not row:
        raise Stage7K5RuntimeError(
            f"inventory position missing for branch/product {branch_id}/{product_id}"
        )
    return dict(row), str(row["feature_as_of_date"])


def _expiry_features(conn, branch_id: str, product_id: str, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        EXPIRY_FEATURE_SQL,
        (branch_id, product_id, branch_id, product_id, int(limit)),
    ).fetchall()
    return [dict(row) for row in rows]


def _resolve_affected(
    conn, change: CdcChange, max_keys: int
) -> tuple[set[tuple[str, str]], set[str]]:
    row = change.row
    pairs: set[tuple[str, str]] = set()
    products: set[str] = set()

    branch_id = row.get("branch_id")
    product_id = row.get("product_id")
    if branch_id and product_id:
        pairs.add((str(branch_id), str(product_id)))
        products.add(str(product_id))

    if change.table == "pos.sale_line":
        product = row.get("product_id")
        sale_id = row.get("sale_id")
        if product:
            products.add(str(product))
        if sale_id and product:
            header = conn.execute(
                "SELECT branch_id::text AS branch_id FROM pos.sale_header WHERE sale_id = %s::uuid",
                (sale_id,),
            ).fetchone()
            if header:
                pairs.add((str(header["branch_id"]), str(product)))

    elif change.table == "pos.sale_header":
        sale_id = row.get("sale_id")
        branch = row.get("branch_id")
        if sale_id:
            rows = conn.execute(
                "SELECT product_id::text AS product_id FROM pos.sale_line WHERE sale_id = %s::uuid",
                (sale_id,),
            ).fetchall()
            for item in rows:
                products.add(str(item["product_id"]))
                if branch:
                    pairs.add((str(branch), str(item["product_id"])))

    elif change.table == "procurement.purchase_order_line":
        po_id = row.get("purchase_order_id")
        product = row.get("product_id")
        if po_id and product:
            header = conn.execute(
                "SELECT branch_id::text AS branch_id FROM procurement.purchase_order "
                "WHERE purchase_order_id = %s::uuid",
                (po_id,),
            ).fetchone()
            if header:
                pairs.add((str(header["branch_id"]), str(product)))
                products.add(str(product))

    elif change.table == "procurement.purchase_order":
        po_id = row.get("purchase_order_id")
        branch = row.get("branch_id")
        if po_id and branch:
            rows = conn.execute(
                "SELECT product_id::text AS product_id FROM procurement.purchase_order_line "
                "WHERE purchase_order_id = %s::uuid LIMIT %s",
                (po_id, max_keys + 1),
            ).fetchall()
            for item in rows:
                product = str(item["product_id"])
                pairs.add((str(branch), product))
                products.add(product)

    elif change.table == "procurement.supplier":
        supplier_id = row.get("supplier_id")
        if supplier_id:
            rows = conn.execute(
                "SELECT DISTINCT po.branch_id::text AS branch_id, "
                "pol.product_id::text AS product_id "
                "FROM procurement.purchase_order po "
                "JOIN procurement.purchase_order_line pol USING (purchase_order_id) "
                "WHERE po.supplier_id = %s::uuid LIMIT %s",
                (supplier_id, max_keys + 1),
            ).fetchall()
            for item in rows:
                pair = (str(item["branch_id"]), str(item["product_id"]))
                pairs.add(pair)
                products.add(pair[1])

    if len(pairs) > max_keys or len(products) > max_keys:
        raise Stage7K5RuntimeError(
            "affected-key fanout exceeds safety cap "
            f"{max_keys}: pairs={len(pairs)} products={len(products)}"
        )
    return pairs, products


def _source_seen(conn, source_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 AS seen FROM mlops.online_source_event WHERE source_event_id = %s",
        (source_id,),
    ).fetchone()
    return bool(row)


def _quarantine_invalid_source(conn, message, exc: Exception) -> str:
    event_id = source_event_id(message.topic(), message.partition(), message.offset())
    raw_value = message.value()
    if isinstance(raw_value, bytes):
        raw_payload = raw_value.decode("utf-8", errors="replace")
    elif raw_value is None:
        raw_payload = None
    else:
        raw_payload = str(raw_value)
    conn.execute(
        """
        INSERT INTO mlops.online_source_quarantine (
            source_event_id, topic, partition_id, offset_value, raw_payload,
            error_class, error_message
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_event_id) DO NOTHING
        """,
        (
            event_id,
            message.topic(),
            message.partition(),
            message.offset(),
            raw_payload,
            type(exc).__name__,
            str(exc),
        ),
    )
    conn.commit()
    return event_id


def _insert_source_event(conn, change: CdcChange, affected_count: int) -> None:
    source_ts = None
    if change.source_ts_ms is not None:
        source_ts = datetime.fromtimestamp(change.source_ts_ms / 1000.0, tz=UTC)
    conn.execute(
        """
        INSERT INTO mlops.online_source_event (
            source_event_id, topic, partition_id, offset_value, source_schema, source_table,
            source_operation, source_event_ts, affected_key_count
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_event_id) DO NOTHING
        """,
        (
            change.event_id,
            change.topic,
            change.partition,
            change.offset,
            change.source_schema,
            change.source_table,
            change.operation,
            source_ts,
            affected_count,
        ),
    )


def _insert_smoke_source(
    conn, source_id: str, smoke_offset: int, affected_count: int
) -> None:
    conn.execute(
        """
        INSERT INTO mlops.online_source_event (
            source_event_id, topic, partition_id, offset_value, source_schema, source_table,
            source_operation, source_event_ts, affected_key_count
        ) VALUES (
            %s, '__stage7k5_smoke__', 0, %s, 'mlops', 'acceptance_smoke', 's', now(), %s
        )
        ON CONFLICT (source_event_id) DO NOTHING
        """,
        (source_id, smoke_offset, affected_count),
    )


def _enqueue_prediction(
    conn,
    *,
    source_id: str,
    model_key: str,
    model_version: str,
    entity_type: str,
    entity_key: str,
    output_topic: str,
    kafka_key: str,
    payload: dict[str, Any],
) -> str:
    event_id = prediction_event_id(source_id, model_key, entity_type, entity_key)
    body = dict(payload)
    body["prediction_event_id"] = event_id
    conn.execute(
        """
        INSERT INTO mlops.prediction_event (
            prediction_event_id, source_event_id, model_key, model_version, entity_type,
            entity_key, output_topic, kafka_key, payload
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (prediction_event_id) DO NOTHING
        """,
        (
            event_id,
            source_id,
            model_key,
            model_version,
            entity_type,
            entity_key,
            output_topic,
            kafka_key,
            _jsonb(body),
        ),
    )
    conn.execute(
        """
        INSERT INTO mlops.prediction_outbox (
            prediction_event_id, output_topic, kafka_key, payload
        ) VALUES (%s, %s, %s, %s)
        ON CONFLICT (prediction_event_id) DO NOTHING
        """,
        (event_id, output_topic, kafka_key, _jsonb(body)),
    )
    return event_id


def _upsert_demand(
    conn, product_id: str, version: str, as_of: str, values: list[float], source_id: str
) -> None:
    conn.execute(
        """
        INSERT INTO mlops.latest_demand_forecast (
            product_id, model_version, feature_as_of_date, demand_1d, demand_7d,
            demand_14d, demand_30d, source_event_id, updated_at
        ) VALUES (%s::uuid, %s, %s::date, %s, %s, %s, %s, %s, now())
        ON CONFLICT (product_id) DO UPDATE SET
            model_version = EXCLUDED.model_version,
            feature_as_of_date = EXCLUDED.feature_as_of_date,
            demand_1d = EXCLUDED.demand_1d,
            demand_7d = EXCLUDED.demand_7d,
            demand_14d = EXCLUDED.demand_14d,
            demand_30d = EXCLUDED.demand_30d,
            source_event_id = EXCLUDED.source_event_id,
            updated_at = now()
        """,
        (product_id, version, as_of, *values, source_id),
    )


def _stockout_alert_state(conn, branch_id: str, product_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT last_severity, last_probability, last_alert_at
        FROM mlops.alert_state
        WHERE branch_id = %s::uuid AND product_id = %s::uuid AND alert_type = 'stockout_risk'
        """,
        (branch_id, product_id),
    ).fetchone()
    return None if row is None else dict(row)


def _upsert_alert_state(
    conn,
    branch_id: str,
    product_id: str,
    severity: str,
    probability: float,
    actionable: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO mlops.alert_state (
            branch_id, product_id, alert_type, last_severity, last_probability,
            last_alert_at, updated_at
        ) VALUES (
            %s::uuid, %s::uuid, 'stockout_risk', %s, %s,
            CASE WHEN %s THEN now() ELSE NULL END, now()
        )
        ON CONFLICT (branch_id, product_id, alert_type) DO UPDATE SET
            last_severity = EXCLUDED.last_severity,
            last_probability = EXCLUDED.last_probability,
            last_alert_at = CASE
                WHEN %s THEN now() ELSE mlops.alert_state.last_alert_at
            END,
            updated_at = now()
        """,
        (branch_id, product_id, severity, probability, actionable, actionable),
    )


def _upsert_branch_decision(
    conn,
    *,
    branch_id: str,
    product_id: str,
    model_key: str,
    version: str,
    as_of: str,
    prediction: float,
    probability: float | None,
    threshold: float | None,
    action_required: bool,
    severity: str,
    source_id: str,
) -> None:
    conn.execute(
        """
        INSERT INTO mlops.latest_branch_product_decision (
            branch_id, product_id, model_key, model_version, feature_as_of_date,
            prediction_value, probability, threshold, action_required, severity,
            source_event_id, updated_at
        ) VALUES (
            %s::uuid, %s::uuid, %s, %s, %s::date, %s, %s, %s, %s, %s, %s, now()
        )
        ON CONFLICT (branch_id, product_id, model_key) DO UPDATE SET
            model_version = EXCLUDED.model_version,
            feature_as_of_date = EXCLUDED.feature_as_of_date,
            prediction_value = EXCLUDED.prediction_value,
            probability = EXCLUDED.probability,
            threshold = EXCLUDED.threshold,
            action_required = EXCLUDED.action_required,
            severity = EXCLUDED.severity,
            source_event_id = EXCLUDED.source_event_id,
            updated_at = now()
        """,
        (
            branch_id,
            product_id,
            model_key,
            version,
            as_of,
            prediction,
            probability,
            threshold,
            action_required,
            severity,
            source_id,
        ),
    )


def _upsert_expiry(
    conn,
    *,
    batch: dict[str, Any],
    version: str,
    probability: float,
    threshold: float,
    high_risk: bool,
    source_id: str,
) -> None:
    conn.execute(
        """
        INSERT INTO mlops.latest_expiry_risk (
            batch_id, branch_id, product_id, model_version, feature_as_of_date,
            probability, threshold, high_risk, days_to_expiry, quantity_on_hand,
            source_event_id, updated_at
        ) VALUES (
            %s::uuid, %s::uuid, %s::uuid, %s, %s::date, %s, %s, %s, %s, %s, %s, now()
        )
        ON CONFLICT (batch_id) DO UPDATE SET
            branch_id = EXCLUDED.branch_id,
            product_id = EXCLUDED.product_id,
            model_version = EXCLUDED.model_version,
            feature_as_of_date = EXCLUDED.feature_as_of_date,
            probability = EXCLUDED.probability,
            threshold = EXCLUDED.threshold,
            high_risk = EXCLUDED.high_risk,
            days_to_expiry = EXCLUDED.days_to_expiry,
            quantity_on_hand = EXCLUDED.quantity_on_hand,
            source_event_id = EXCLUDED.source_event_id,
            updated_at = now()
        """,
        (
            batch["batch_id"],
            batch["branch_id"],
            batch["product_id"],
            version,
            str(batch["feature_as_of_date"]),
            probability,
            threshold,
            high_risk,
            int(batch["days_to_expiry"]),
            int(batch["quantity_on_hand"]),
            source_id,
        ),
    )


def _process_entities(
    conn,
    *,
    source_id: str,
    pairs: set[tuple[str, str]],
    products: set[str],
    model_api_uri: str,
    metadata: dict[str, dict[str, Any]],
    cooldown_seconds: int,
    max_expiry_batches: int,
    smoke: bool = False,
) -> int:
    emitted = 0
    now = datetime.now(UTC)

    demand_meta = metadata["demand_forecast"]
    for product_id in sorted(products):
        features, as_of = _demand_features(conn, product_id)
        response = _predict(model_api_uri, "demand_forecast", features)
        values = [float(v) for v in response["prediction"][0]]
        if len(values) != 4:
            raise Stage7K5RuntimeError("demand model did not return four horizons")
        version = str(response["version"])
        _upsert_demand(conn, product_id, version, as_of, values, source_id)
        payload = {
            "stage": "7K.5",
            "model_key": "demand_forecast",
            "model_version": version,
            "product_id": product_id,
            "feature_as_of_date": as_of,
            "forecast": {
                "demand_1d": values[0],
                "demand_7d": values[1],
                "demand_14d": values[2],
                "demand_30d": values[3],
            },
            "acceptance_smoke": smoke,
            "generated_at": now.isoformat(),
        }
        _enqueue_prediction(
            conn,
            source_id=source_id,
            model_key="demand_forecast",
            model_version=str(demand_meta.get("version") or version),
            entity_type="PRODUCT",
            entity_key=product_id,
            output_topic=DEMAND_FORECAST_TOPIC,
            kafka_key=product_id,
            payload=payload,
        )
        emitted += 1

    stockout_meta = metadata["stockout_risk"]
    reorder_meta = metadata["reorder_recommendation"]
    expiry_meta = metadata["expiry_slow_moving_risk"]
    stockout_threshold = numeric(stockout_meta.get("threshold"), 0.001)
    expiry_threshold = numeric(expiry_meta.get("threshold"), 0.50)

    stockout_keys = [
        "available_units",
        "requested_avg_7",
        "requested_avg_28",
        "requested_stddev_28",
        "lost_rate_28",
        "stockout_rate_28",
        "supplier_lead_time_days",
        "supplier_reliability",
        "day_of_week",
        "month_of_year",
    ]
    reorder_keys = [
        "available_units",
        "avg_daily_requested_units",
        "demand_stddev_units",
        "supplier_lead_time_days",
        "supplier_reliability",
        "inbound_units",
    ]
    expiry_keys = [
        "days_to_expiry",
        "quantity_on_hand",
        "avg_daily_units_sold",
        "demand_stddev_units",
    ]

    for branch_id, product_id in sorted(pairs):
        row, as_of = _branch_product_features(conn, branch_id, product_id)

        stockout_response = _predict(
            model_api_uri, "stockout_risk", _finite_feature_dict(row, stockout_keys)
        )
        predicted = bool(round(float(stockout_response["prediction"][0])))
        probability = float(stockout_response.get("probability", [0.0])[0])
        threshold = numeric(stockout_meta.get("threshold"), stockout_threshold)
        severity = stockout_severity(probability, threshold, predicted)
        previous = _stockout_alert_state(conn, branch_id, product_id)
        actionable = alert_is_actionable(
            predicted_positive=predicted,
            severity=severity,
            previous_severity=None if previous is None else str(previous["last_severity"]),
            previous_alert_at=None if previous is None else previous["last_alert_at"],
            now=now,
            cooldown_seconds=cooldown_seconds,
        )
        if not smoke:
            _upsert_alert_state(conn, branch_id, product_id, severity, probability, actionable)
        _upsert_branch_decision(
            conn,
            branch_id=branch_id,
            product_id=product_id,
            model_key="stockout_risk",
            version=str(stockout_response["version"]),
            as_of=as_of,
            prediction=float(predicted),
            probability=probability,
            threshold=threshold,
            action_required=actionable,
            severity=severity,
            source_id=source_id,
        )
        stockout_payload = {
            "stage": "7K.5",
            "model_key": "stockout_risk",
            "model_version": str(stockout_response["version"]),
            "branch_id": branch_id,
            "product_id": product_id,
            "feature_as_of_date": as_of,
            "predicted_stockout": predicted,
            "probability": probability,
            "operating_threshold": threshold,
            "severity": severity,
            "action_required": actionable,
            "alert_cooldown_seconds": cooldown_seconds,
            "acceptance_smoke": smoke,
            "generated_at": now.isoformat(),
        }
        _enqueue_prediction(
            conn,
            source_id=source_id,
            model_key="stockout_risk",
            model_version=str(stockout_response["version"]),
            entity_type="BRANCH_PRODUCT",
            entity_key=f"{branch_id}|{product_id}",
            output_topic=STOCKOUT_PREDICTION_TOPIC,
            kafka_key=f"{branch_id}|{product_id}",
            payload=stockout_payload,
        )
        emitted += 1

        reorder_response = _predict(
            model_api_uri,
            "reorder_recommendation",
            _finite_feature_dict(row, reorder_keys),
        )
        units = max(float(reorder_response["prediction"][0]), 0.0)
        reorder_action = units > 0.0
        _upsert_branch_decision(
            conn,
            branch_id=branch_id,
            product_id=product_id,
            model_key="reorder_recommendation",
            version=str(reorder_response["version"]),
            as_of=as_of,
            prediction=units,
            probability=None,
            threshold=None,
            action_required=reorder_action,
            severity="WATCH" if reorder_action else "NORMAL",
            source_id=source_id,
        )
        reorder_payload = {
            "stage": "7K.5",
            "model_key": "reorder_recommendation",
            "model_version": str(reorder_response["version"]),
            "branch_id": branch_id,
            "product_id": product_id,
            "feature_as_of_date": as_of,
            "recommended_order_units": units,
            "action_required": reorder_action,
            "decision_semantics": "LATEST_STATE_NOT_ORDER_COMMAND",
            "acceptance_smoke": smoke,
            "generated_at": now.isoformat(),
        }
        _enqueue_prediction(
            conn,
            source_id=source_id,
            model_key="reorder_recommendation",
            model_version=str(reorder_meta.get("version") or reorder_response["version"]),
            entity_type="BRANCH_PRODUCT",
            entity_key=f"{branch_id}|{product_id}",
            output_topic=REORDER_RECOMMENDATION_TOPIC,
            kafka_key=f"{branch_id}|{product_id}",
            payload=reorder_payload,
        )
        emitted += 1

        for batch in _expiry_features(conn, branch_id, product_id, max_expiry_batches):
            expiry_features = _finite_feature_dict(batch, expiry_keys)
            expiry_response = _predict(
                model_api_uri, "expiry_slow_moving_risk", expiry_features
            )
            high_risk = bool(round(float(expiry_response["prediction"][0])))
            probability = float(expiry_response.get("probability", [0.0])[0])
            threshold = numeric(expiry_meta.get("threshold"), expiry_threshold)
            _upsert_expiry(
                conn,
                batch=batch,
                version=str(expiry_response["version"]),
                probability=probability,
                threshold=threshold,
                high_risk=high_risk,
                source_id=source_id,
            )
            payload = {
                "stage": "7K.5",
                "model_key": "expiry_slow_moving_risk",
                "model_version": str(expiry_response["version"]),
                "batch_id": batch["batch_id"],
                "branch_id": branch_id,
                "product_id": product_id,
                "feature_as_of_date": str(batch["feature_as_of_date"]),
                "days_to_expiry": int(batch["days_to_expiry"]),
                "quantity_on_hand": int(batch["quantity_on_hand"]),
                "probability": probability,
                "operating_threshold": threshold,
                "high_risk": high_risk,
                "action_required": high_risk,
                "acceptance_smoke": smoke,
                "generated_at": now.isoformat(),
            }
            _enqueue_prediction(
                conn,
                source_id=source_id,
                model_key="expiry_slow_moving_risk",
                model_version=str(expiry_response["version"]),
                entity_type="BATCH",
                entity_key=str(batch["batch_id"]),
                output_topic=EXPIRY_ALERT_TOPIC,
                kafka_key=str(batch["batch_id"]),
                payload=payload,
            )
            emitted += 1

    return emitted


class _KafkaDeliveryTracker:
    """Capture one synchronous Kafka delivery result without loop-closure state."""

    def __init__(self) -> None:
        self.delivered = False
        self.errors: list[str] = []

    def callback(self, err, _message) -> None:
        if err is not None:
            self.errors.append(str(err))
        else:
            self.delivered = True


def _publish_pending(conn, producer, limit: int = 1000) -> int:
    rows = conn.execute(
        """
        SELECT prediction_event_id, output_topic, kafka_key, payload
        FROM mlops.prediction_outbox
        WHERE published_at IS NULL
        ORDER BY created_at, prediction_event_id
        LIMIT %s
        """,
        (limit,),
    ).fetchall()
    published = 0
    for row in rows:
        delivery = _KafkaDeliveryTracker()

        payload = row["payload"]
        body = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"))
        producer.produce(
            str(row["output_topic"]),
            key=str(row["kafka_key"]).encode(),
            value=body.encode(),
            headers=[
                ("content-type", b"application/json"),
                ("prediction-event-id", str(row["prediction_event_id"]).encode()),
                ("source", b"pharmstock-stage7k5"),
            ],
            on_delivery=delivery.callback,
        )
        remaining = producer.flush(15)
        if delivery.errors or remaining or not delivery.delivered:
            message = delivery.errors[0] if delivery.errors else "Kafka delivery timeout"
            conn.execute(
                """
                UPDATE mlops.prediction_outbox
                SET publish_attempts = publish_attempts + 1, last_error = %s
                WHERE prediction_event_id = %s
                """,
                (message, row["prediction_event_id"]),
            )
            conn.commit()
            raise Stage7K5RuntimeError(message)
        conn.execute(
            """
            UPDATE mlops.prediction_outbox
            SET publish_attempts = publish_attempts + 1, published_at = now(), last_error = NULL
            WHERE prediction_event_id = %s
            """,
            (row["prediction_event_id"],),
        )
        conn.commit()
        published += 1
    return published


def _operational_metrics(conn) -> dict[str, int | float]:
    row = conn.execute(
        """
        SELECT
            COUNT(*)::integer AS pending_outbox,
            COALESCE(MAX(publish_attempts), 0)::integer AS max_publish_attempts,
            COALESCE(
                EXTRACT(EPOCH FROM (now() - MIN(created_at))),
                0
            )::double precision AS oldest_pending_outbox_seconds
        FROM mlops.prediction_outbox
        WHERE published_at IS NULL
        """
    ).fetchone()
    quarantined = conn.execute(
        "SELECT COUNT(*)::integer AS n FROM mlops.online_source_quarantine"
    ).fetchone()["n"]
    return {
        "pending_outbox": int(row["pending_outbox"]),
        "max_publish_attempts": int(row["max_publish_attempts"]),
        "oldest_pending_outbox_seconds": float(row["oldest_pending_outbox_seconds"]),
        "quarantine_rows": int(quarantined),
    }


def _write_heartbeat(
    stats: WorkerStats,
    status: str = "HEALTHY",
    *,
    conn=None,
) -> None:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "status": status,
        "updated_at": datetime.now(UTC).isoformat(),
        "processed_events": stats.processed_events,
        "duplicate_events": stats.duplicate_events,
        "quarantined_events": stats.quarantined_events,
        "emitted_predictions": stats.emitted_predictions,
        "published_outbox": stats.published_outbox,
        "retry_attempt": stats.retry_attempt,
        "last_source_event_id": stats.last_source_event_id,
        "last_error": stats.last_error,
        "cloud_mutation": False,
    }
    if conn is not None:
        # Heartbeat metrics are read-only. With psycopg
        # autocommit=False, SELECT statements implicitly
        # open a transaction. Close that read transaction
        # immediately so the long-running Kafka worker
        # cannot remain idle in transaction between polls
        # or during retry backoff.
        payload.update(_operational_metrics(conn))
        conn.rollback()

    HEARTBEAT_PATH.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def healthcheck() -> None:
    max_age = int(
        os.getenv(
            "PHARMSTOCK_STAGE7K5_HEARTBEAT_MAX_AGE_SECONDS",
            str(DEFAULT_HEARTBEAT_MAX_AGE_SECONDS),
        )
    )
    max_pending = int(
        os.getenv("PHARMSTOCK_STAGE7K5_MAX_PENDING_OUTBOX", str(DEFAULT_MAX_PENDING_OUTBOX))
    )
    max_pending_age = int(
        os.getenv(
            "PHARMSTOCK_STAGE7K5_MAX_PENDING_OUTBOX_AGE_SECONDS",
            str(DEFAULT_MAX_PENDING_OUTBOX_AGE_SECONDS),
        )
    )
    if not HEARTBEAT_PATH.is_file():
        raise Stage7K5RuntimeError("worker heartbeat file is missing")
    heartbeat = json.loads(HEARTBEAT_PATH.read_text(encoding="utf-8"))
    updated_at = datetime.fromisoformat(str(heartbeat["updated_at"]))
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    heartbeat_age = max((datetime.now(UTC) - updated_at).total_seconds(), 0.0)
    if heartbeat.get("status") != "HEALTHY" or heartbeat_age > max_age:
        heartbeat_status = heartbeat.get("status")
        raise Stage7K5RuntimeError(
            f"worker heartbeat unhealthy/stale: status={heartbeat_status} "
            f"age={heartbeat_age:.1f}s"
        )

    config = config_from_environment()
    _model_metadata(config.model_api_uri)
    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:19092")
    try:
        from confluent_kafka.admin import AdminClient
    except ModuleNotFoundError as exc:
        raise Stage7K5RuntimeError("confluent-kafka is required by Stage 7K.5") from exc
    topics = set(
        AdminClient({"bootstrap.servers": bootstrap_servers})
        .list_topics(timeout=10)
        .topics
    )
    missing = [item.name for item in ML_OUTPUT_TOPICS if item.name not in topics]
    if missing:
        raise Stage7K5RuntimeError(f"ML output topics missing during healthcheck: {missing}")

    with _pg_connect() as conn:
        metrics = _operational_metrics(conn)
    if int(metrics["pending_outbox"]) > max_pending:
        raise Stage7K5RuntimeError(f"pending outbox exceeds health limit: {metrics}")
    if float(metrics["oldest_pending_outbox_seconds"]) > max_pending_age:
        raise Stage7K5RuntimeError(f"pending outbox is stale: {metrics}")

    print(
        "STAGE_7K5_HEALTHCHECK_STATUS=PASS "
        f"heartbeat_age={heartbeat_age:.1f}s pending={metrics['pending_outbox']} "
        f"quarantine={metrics['quarantine_rows']}"
    )


def _process_change(conn, change: CdcChange, metadata: dict[str, dict[str, Any]], config) -> int:
    if _source_seen(conn, change.event_id):
        return -1
    pairs, products = _resolve_affected(conn, change, config.max_affected_keys)
    _insert_source_event(conn, change, len(pairs) + len(products))
    emitted = _process_entities(
        conn,
        source_id=change.event_id,
        pairs=pairs,
        products=products,
        model_api_uri=config.model_api_uri,
        metadata=metadata,
        cooldown_seconds=config.alert_cooldown_seconds,
        max_expiry_batches=config.max_expiry_batches_per_key,
    )
    conn.commit()
    return emitted


def _smoke_candidate(conn) -> tuple[str, str]:
    row = conn.execute(
        """
        SELECT i.branch_id::text AS branch_id, i.product_id::text AS product_id
        FROM inventory.inventory_position i
        WHERE EXISTS (
            SELECT 1 FROM pos.demand_attempt d
            WHERE d.branch_id = i.branch_id AND d.product_id = i.product_id
        )
          AND EXISTS (
            SELECT 1 FROM inventory.stock_batch b
            WHERE b.branch_id = i.branch_id
              AND b.product_id = i.product_id
              AND b.quantity_on_hand > 0
              AND UPPER(COALESCE(b.status, 'ACTIVE')) = 'ACTIVE'
        )
        ORDER BY i.last_movement_at DESC NULLS LAST, i.branch_id, i.product_id
        LIMIT 1
        """
    ).fetchone()
    if not row:
        raise Stage7K5RuntimeError(
            "no branch/product with inventory + demand history for smoke test"
        )
    return str(row["branch_id"]), str(row["product_id"])


def smoke() -> None:
    config = config_from_environment()
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:19092")
    topics = _ensure_output_topics(bootstrap)
    metadata = _model_metadata(config.model_api_uri)
    producer = _producer(bootstrap)
    with _pg_connect() as conn:
        branch_id, product_id = _smoke_candidate(conn)
        smoke_offset = time.time_ns()
        source_id = f"stage7k5-smoke-{smoke_offset}-{os.getpid()}"
        _insert_smoke_source(conn, source_id, smoke_offset, 2)
        emitted = _process_entities(
            conn,
            source_id=source_id,
            pairs={(branch_id, product_id)},
            products={product_id},
            model_api_uri=config.model_api_uri,
            metadata=metadata,
            cooldown_seconds=config.alert_cooldown_seconds,
            max_expiry_batches=config.max_expiry_batches_per_key,
            smoke=True,
        )
        conn.commit()
        published = _publish_pending(conn, producer)
        pending = conn.execute(
            "SELECT COUNT(*) AS n FROM mlops.prediction_outbox WHERE published_at IS NULL"
        ).fetchone()["n"]
        latest = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM mlops.latest_demand_forecast) AS demand_rows,
                (SELECT COUNT(*) FROM mlops.latest_branch_product_decision) AS branch_rows,
                (SELECT COUNT(*) FROM mlops.latest_expiry_risk) AS expiry_rows
            """
        ).fetchone()

    report = {
        "status": (
            "PASS" if emitted >= 4 and published >= emitted and int(pending) == 0 else "FAIL"
        ),
        "source_event_id": source_id,
        "branch_id": branch_id,
        "product_id": product_id,
        "output_topics": list(topics),
        "emitted_predictions": emitted,
        "published_predictions": published,
        "pending_outbox": int(pending),
        "latest_store": {key: int(value) for key, value in dict(latest).items()},
        "models": {key: str(value.get("version")) for key, value in metadata.items()},
        "cloud_mutation": False,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    SMOKE_REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("=== PharmStock Stage 7K.5 / Online Decision Smoke ===")
    print(f"Candidate:             {branch_id} / {product_id}")
    print(f"Output topics:         {len(topics)}")
    print(f"Predictions emitted:   {emitted}")
    print(f"Outbox published:      {published}")
    print(f"Outbox pending:        {pending}")
    print(f"Operational store:     {dict(latest)}")
    print("Cloud mutation:        NO")
    if report["status"] != "PASS":
        raise Stage7K5RuntimeError(f"smoke validation failed: {report}")
    print("STAGE_7K5_SMOKE_STATUS=PASS")


def bootstrap() -> None:
    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:19092")
    topics = _ensure_output_topics(bootstrap_servers)
    metadata = _model_metadata(config_from_environment().model_api_uri)
    with _pg_connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM pg_publication_tables "
            "WHERE pubname = 'pharmstock_cdc_publication' AND schemaname = 'mlops'"
        ).fetchone()
        if int(row["n"]) != 0:
            raise Stage7K5RuntimeError("mlops tables unexpectedly present in CDC publication")
    print("=== PharmStock Stage 7K.5 / Bootstrap ===")
    print(f"ML output topics:      {len(topics)}")
    print(f"Production champions: {len(metadata)}/4")
    print("ML feedback into CDC:  BLOCKED")
    print("Cloud mutation:        NO")
    print("STAGE_7K5_BOOTSTRAP_STATUS=PASS")


def run_forever() -> None:
    config = config_from_environment()
    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:19092")
    _ensure_output_topics(bootstrap_servers)
    metadata = _model_metadata(config.model_api_uri)
    producer = _producer(bootstrap_servers)
    consumer = _consumer(bootstrap_servers, config.consumer_group)
    stats = WorkerStats()
    stop = False

    def request_stop(_signum, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    print("=== PharmStock Stage 7K.5 / CDC-Triggered Online ML Worker ===", flush=True)
    print(f"Consumer group:        {config.consumer_group}", flush=True)
    print(f"CDC trigger topics:    {len(MONITORED_CDC_TOPICS)}", flush=True)
    print(f"Model API:             {config.model_api_uri}", flush=True)
    print("Feature source:        POSTGRES READ-THROUGH", flush=True)
    print("Invalid CDC policy:    DURABLE QUARANTINE + OFFSET COMMIT", flush=True)
    print("Retry policy:          BOUNDED EXPONENTIAL BACKOFF", flush=True)
    print("Cloud mutation:        NO", flush=True)

    try:
        with _pg_connect() as conn:
            stats.published_outbox += _publish_pending(conn, producer)
            _write_heartbeat(stats, conn=conn)
            while not stop:
                message = consumer.poll(1.0)
                if message is None:
                    _write_heartbeat(stats, conn=conn)
                    continue
                if message.error():
                    raise Stage7K5RuntimeError(str(message.error()))

                try:
                    change = decode_debezium_change(
                        message.value(),
                        topic=message.topic(),
                        partition=message.partition(),
                        offset=message.offset(),
                    )
                except Exception as exc:
                    conn.rollback()
                    quarantined_id = _quarantine_invalid_source(conn, message, exc)
                    stats.quarantined_events += 1
                    stats.last_source_event_id = quarantined_id
                    stats.last_error = f"invalid CDC quarantined: {exc}"
                    stats.retry_attempt = 0
                    consumer.commit(message=message, asynchronous=False)
                    _write_heartbeat(stats, conn=conn)
                    print(
                        f"Stage 7K.5 quarantined invalid CDC event: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )
                    continue

                retry_attempt = 0
                while not stop:
                    try:
                        emitted = _process_change(conn, change, metadata, config)
                        if emitted < 0:
                            stats.duplicate_events += 1
                        else:
                            stats.processed_events += 1
                            stats.emitted_predictions += emitted
                        stats.published_outbox += _publish_pending(conn, producer)
                        stats.last_source_event_id = change.event_id
                        stats.last_error = None
                        stats.retry_attempt = 0
                        consumer.commit(message=message, asynchronous=False)
                        _write_heartbeat(stats, conn=conn)
                        break
                    except Exception as exc:
                        conn.rollback()
                        retry_attempt += 1
                        stats.retry_attempt = retry_attempt
                        stats.last_error = str(exc)
                        _write_heartbeat(stats, status="DEGRADED", conn=conn)
                        backoff = min(
                            2 ** min(retry_attempt, 10),
                            config.max_processing_backoff_seconds,
                        )
                        print(
                            "Stage 7K.5 processing retry "
                            f"attempt={retry_attempt} backoff={backoff}s: {exc}",
                            file=sys.stderr,
                            flush=True,
                        )
                        time.sleep(float(backoff))
    finally:
        consumer.close()
        try:
            with _pg_connect() as conn:
                _write_heartbeat(stats, status="STOPPED" if stop else "FAILED", conn=conn)
        except Exception:
            _write_heartbeat(stats, status="STOPPED" if stop else "FAILED")

def main() -> None:
    parser = argparse.ArgumentParser(description="PharmStock Stage 7K.5 online ML worker")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--bootstrap-only", action="store_true")
    mode.add_argument("--smoke", action="store_true")
    mode.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    if args.bootstrap_only:
        bootstrap()
    elif args.smoke:
        smoke()
    elif args.healthcheck:
        healthcheck()
    else:
        run_forever()


if __name__ == "__main__":
    main()
