\set ON_ERROR_STOP on

-- ============================================================
-- PharmStock AI - Stage 7O
-- Governed read-serving layer for the standalone AI Assistant.
--
-- Security model:
--   Assistant -> Stage 7M API -> assistant_api views
--   No direct Assistant database credentials
--   No procurement mutation
--   No unrestricted raw-table access
-- ============================================================

CREATE SCHEMA IF NOT EXISTS assistant_api;

REVOKE ALL ON SCHEMA assistant_api FROM PUBLIC;
GRANT USAGE ON SCHEMA assistant_api TO pharmstock_workbench;


-- ============================================================
-- 1. Current inventory context
-- Grain: Branch x Product
-- ============================================================

CREATE OR REPLACE VIEW assistant_api.v_inventory_context
WITH (
    security_barrier = true,
    security_invoker = false
)
AS
SELECT
    ip.branch_id,
    b.branch_code,
    b.display_name AS branch_name,
    b.governorate,
    b.representative_city,

    ip.product_id,
    p.trade_name_en,
    p.trade_name_ar,
    p.scientific_name,
    p.manufacturer,

    ip.on_hand_units,
    ip.reserved_units,
    ip.available_units,
    ip.reorder_point_units,
    ip.target_stock_units,

    (ip.available_units = 0) AS zero_stock,
    (ip.available_units <= ip.reorder_point_units) AS below_reorder,

    ip.last_movement_at,
    ip.version AS inventory_version,
    ip.updated_at
FROM inventory.inventory_position AS ip
JOIN master.pharmacy_branch AS b
  ON b.branch_id = ip.branch_id
JOIN master.product AS p
  ON p.product_id = ip.product_id;


-- ============================================================
-- 2. Latest governed ML signals
-- Reuses the curated Stage 7N serving view so acceptance-smoke
-- rows stay excluded.
-- Grain: Branch x Product x Model
-- ============================================================

CREATE OR REPLACE VIEW assistant_api.v_ml_signal
WITH (
    security_barrier = true,
    security_invoker = false
)
AS
SELECT
    branch_id,
    branch_code,
    branch_name,
    governorate,
    representative_city,

    product_id,
    trade_name_en,
    trade_name_ar,
    scientific_name,
    manufacturer,

    model_key,
    model_version,
    feature_as_of_date,
    prediction_value,
    probability,
    threshold,
    action_required,
    severity,
    updated_at
FROM bi.v_ml_branch_product_decision;


-- ============================================================
-- 3. Recent demand context
--
-- Anchor is the latest observed operational demand timestamp.
-- In live production this naturally tracks current activity.
-- It also keeps a static validation dataset reproducible.
--
-- Grain: Branch x Product
-- ============================================================

CREATE OR REPLACE VIEW assistant_api.v_demand_context
WITH (
    security_barrier = true,
    security_invoker = false
)
AS
WITH anchor AS (
    SELECT MAX(transaction_ts) AS data_as_of
    FROM pos.demand_attempt
),
agg AS (
    SELECT
        d.branch_id,
        d.product_id,
        a.data_as_of,

        MAX(d.transaction_ts) AS latest_demand_at,

        COUNT(*) FILTER (
            WHERE d.transaction_ts >= a.data_as_of - INTERVAL '7 days'
        )::integer AS demand_attempts_7d,

        COALESCE(SUM(d.requested_units) FILTER (
            WHERE d.transaction_ts >= a.data_as_of - INTERVAL '7 days'
        ), 0)::bigint AS requested_units_7d,

        COALESCE(SUM(d.fulfilled_units) FILTER (
            WHERE d.transaction_ts >= a.data_as_of - INTERVAL '7 days'
        ), 0)::bigint AS fulfilled_units_7d,

        COALESCE(SUM(d.lost_units) FILTER (
            WHERE d.transaction_ts >= a.data_as_of - INTERVAL '7 days'
        ), 0)::bigint AS lost_units_7d,

        COUNT(*) FILTER (
            WHERE d.transaction_ts >= a.data_as_of - INTERVAL '7 days'
              AND d.outcome = 'OUT_OF_STOCK'
        )::integer AS stockout_attempts_7d,

        COUNT(*)::integer AS demand_attempts_28d,
        COALESCE(SUM(d.requested_units), 0)::bigint AS requested_units_28d,
        COALESCE(SUM(d.fulfilled_units), 0)::bigint AS fulfilled_units_28d,
        COALESCE(SUM(d.lost_units), 0)::bigint AS lost_units_28d,

        COUNT(*) FILTER (
            WHERE d.outcome = 'OUT_OF_STOCK'
        )::integer AS stockout_attempts_28d

    FROM pos.demand_attempt AS d
    CROSS JOIN anchor AS a
    WHERE a.data_as_of IS NOT NULL
      AND d.transaction_ts >= a.data_as_of - INTERVAL '28 days'
    GROUP BY
        d.branch_id,
        d.product_id,
        a.data_as_of
)
SELECT
    a.branch_id,
    b.branch_code,
    b.display_name AS branch_name,
    b.governorate,
    b.representative_city,

    a.product_id,
    p.trade_name_en,
    p.trade_name_ar,
    p.scientific_name,
    p.manufacturer,

    a.data_as_of,
    a.latest_demand_at,

    a.demand_attempts_7d,
    a.requested_units_7d,
    a.fulfilled_units_7d,
    a.lost_units_7d,
    a.stockout_attempts_7d,

    CASE
        WHEN a.requested_units_7d > 0
        THEN ROUND(
            a.fulfilled_units_7d::numeric /
            a.requested_units_7d::numeric,
            6
        )
        ELSE NULL
    END AS fill_rate_7d,

    a.demand_attempts_28d,
    a.requested_units_28d,
    a.fulfilled_units_28d,
    a.lost_units_28d,
    a.stockout_attempts_28d,

    CASE
        WHEN a.requested_units_28d > 0
        THEN ROUND(
            a.fulfilled_units_28d::numeric /
            a.requested_units_28d::numeric,
            6
        )
        ELSE NULL
    END AS fill_rate_28d

FROM agg AS a
JOIN master.pharmacy_branch AS b
  ON b.branch_id = a.branch_id
JOIN master.product AS p
  ON p.product_id = a.product_id;


-- ============================================================
-- 4. Supplier performance context
-- Read-only analytical context.
-- No supplier selection or procurement execution is exposed.
-- ============================================================

CREATE OR REPLACE VIEW assistant_api.v_supplier_context
WITH (
    security_barrier = true,
    security_invoker = false
)
AS
WITH po_stats AS (
    SELECT
        po.supplier_id,

        COUNT(*)::integer AS purchase_order_count,

        COUNT(*) FILTER (
            WHERE po.status = 'RECEIVED'
        )::integer AS received_po_count,

        COUNT(*) FILTER (
            WHERE po.status NOT IN ('RECEIVED', 'CANCELLED')
        )::integer AS open_po_count,

        COALESCE(SUM(po.ordered_cost_egp), 0)::numeric
            AS ordered_cost_egp,

        MAX(po.ordered_at) AS latest_ordered_at

    FROM procurement.purchase_order AS po
    GROUP BY po.supplier_id
),
receipt_stats AS (
    SELECT
        gr.supplier_id,

        COUNT(*)::integer AS receipt_count,

        AVG(
            EXTRACT(
                EPOCH FROM (gr.received_at - po.ordered_at)
            ) / 86400.0
        )::numeric(12,4) AS avg_actual_lead_time_days,

        COUNT(*) FILTER (
            WHERE po.expected_at IS NOT NULL
              AND gr.received_at > po.expected_at
        )::integer AS delayed_receipt_count,

        COALESCE(SUM(gr.received_cost_egp), 0)::numeric
            AS received_cost_egp,

        MAX(gr.received_at) AS latest_received_at

    FROM procurement.goods_receipt AS gr
    JOIN procurement.purchase_order AS po
      ON po.purchase_order_id = gr.purchase_order_id
    GROUP BY gr.supplier_id
)
SELECT
    s.supplier_id,
    s.supplier_code,
    s.supplier_name,
    s.supplier_type,
    s.service_scope,
    s.reliability_score,
    s.nominal_lead_time_days,
    s.is_active,

    COALESCE(po.purchase_order_count, 0) AS purchase_order_count,
    COALESCE(po.received_po_count, 0) AS received_po_count,
    COALESCE(po.open_po_count, 0) AS open_po_count,
    COALESCE(po.ordered_cost_egp, 0) AS ordered_cost_egp,

    COALESCE(r.receipt_count, 0) AS receipt_count,
    r.avg_actual_lead_time_days,
    COALESCE(r.delayed_receipt_count, 0) AS delayed_receipt_count,

    CASE
        WHEN COALESCE(r.receipt_count, 0) > 0
        THEN ROUND(
            r.delayed_receipt_count::numeric /
            r.receipt_count::numeric,
            6
        )
        ELSE NULL
    END AS delayed_receipt_rate,

    COALESCE(r.received_cost_egp, 0) AS received_cost_egp,

    po.latest_ordered_at,
    r.latest_received_at

FROM procurement.supplier AS s
LEFT JOIN po_stats AS po
  ON po.supplier_id = s.supplier_id
LEFT JOIN receipt_stats AS r
  ON r.supplier_id = s.supplier_id;


-- ============================================================
-- Least-privilege grants
-- ============================================================

REVOKE ALL ON ALL TABLES IN SCHEMA assistant_api FROM PUBLIC;

GRANT SELECT ON assistant_api.v_inventory_context
    TO pharmstock_workbench;

GRANT SELECT ON assistant_api.v_ml_signal
    TO pharmstock_workbench;

GRANT SELECT ON assistant_api.v_demand_context
    TO pharmstock_workbench;

GRANT SELECT ON assistant_api.v_supplier_context
    TO pharmstock_workbench;


-- Explicitly ensure Assistant serving relations cannot be mutated
-- by the Stage 7M workbench role.
REVOKE INSERT, UPDATE, DELETE
ON ALL TABLES IN SCHEMA assistant_api
FROM pharmstock_workbench;
