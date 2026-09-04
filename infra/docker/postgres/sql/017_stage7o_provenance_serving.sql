-- Stage 7O provenance propagation into governed assistant evidence.
--
-- Provenance semantics:
--   operational_provenance_class = provenance of operational/simulated entities.
--   reference_provenance_class   = provenance of product/reference master data.
--
-- Never collapse these into a single MIXED value.
-- Existing view columns remain unchanged and provenance columns are appended.

CREATE OR REPLACE VIEW assistant_api.v_inventory_context AS
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
    ip.available_units = 0 AS zero_stock,
    ip.available_units <= ip.reorder_point_units AS below_reorder,
    ip.last_movement_at,
    ip.version AS inventory_version,
    ip.updated_at,
    b.provenance_class AS operational_provenance_class,
    p.provenance_class AS reference_provenance_class
FROM inventory.inventory_position ip
JOIN master.pharmacy_branch b
  ON b.branch_id = ip.branch_id
JOIN master.product p
  ON p.product_id = ip.product_id;


CREATE OR REPLACE VIEW assistant_api.v_ml_signal AS
SELECT
    m.branch_id,
    m.branch_code,
    m.branch_name,
    m.governorate,
    m.representative_city,
    m.product_id,
    m.trade_name_en,
    m.trade_name_ar,
    m.scientific_name,
    m.manufacturer,
    m.model_key,
    m.model_version,
    m.feature_as_of_date,
    m.prediction_value,
    m.probability,
    m.threshold,
    m.action_required,
    m.severity,
    m.updated_at,
    b.provenance_class AS operational_provenance_class,
    p.provenance_class AS reference_provenance_class
FROM bi.v_ml_branch_product_decision m
LEFT JOIN master.pharmacy_branch b
  ON b.branch_id = m.branch_id
LEFT JOIN master.product p
  ON p.product_id = m.product_id;


CREATE OR REPLACE VIEW assistant_api.v_supplier_context AS
WITH po_stats AS (
    SELECT
        po.supplier_id,
        COUNT(*)::integer AS purchase_order_count,
        COUNT(*) FILTER (
            WHERE po.status = 'RECEIVED'
        )::integer AS received_po_count,
        COUNT(*) FILTER (
            WHERE po.status <> ALL (
                ARRAY['RECEIVED'::text, 'CANCELLED'::text]
            )
        )::integer AS open_po_count,
        COALESCE(
            SUM(po.ordered_cost_egp),
            0::numeric
        ) AS ordered_cost_egp,
        MAX(po.ordered_at) AS latest_ordered_at
    FROM procurement.purchase_order po
    GROUP BY po.supplier_id
),
receipt_stats AS (
    SELECT
        gr.supplier_id,
        COUNT(*)::integer AS receipt_count,
        AVG(
            EXTRACT(
                epoch FROM gr.received_at - po.ordered_at
            ) / 86400.0
        )::numeric(12,4) AS avg_actual_lead_time_days,
        COUNT(*) FILTER (
            WHERE po.expected_at IS NOT NULL
              AND gr.received_at > po.expected_at
        )::integer AS delayed_receipt_count,
        COALESCE(
            SUM(gr.received_cost_egp),
            0::numeric
        ) AS received_cost_egp,
        MAX(gr.received_at) AS latest_received_at
    FROM procurement.goods_receipt gr
    JOIN procurement.purchase_order po
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
    COALESCE(po.purchase_order_count, 0)
        AS purchase_order_count,
    COALESCE(po.received_po_count, 0)
        AS received_po_count,
    COALESCE(po.open_po_count, 0)
        AS open_po_count,
    COALESCE(po.ordered_cost_egp, 0::numeric)
        AS ordered_cost_egp,
    COALESCE(r.receipt_count, 0)
        AS receipt_count,
    r.avg_actual_lead_time_days,
    COALESCE(r.delayed_receipt_count, 0)
        AS delayed_receipt_count,
    CASE
        WHEN COALESCE(r.receipt_count, 0) > 0
        THEN ROUND(
            r.delayed_receipt_count::numeric
            / r.receipt_count::numeric,
            6
        )
        ELSE NULL::numeric
    END AS delayed_receipt_rate,
    COALESCE(r.received_cost_egp, 0::numeric)
        AS received_cost_egp,
    po.latest_ordered_at,
    r.latest_received_at,
    s.provenance_class AS operational_provenance_class,
    NULL::text AS reference_provenance_class
FROM procurement.supplier s
LEFT JOIN po_stats po
  ON po.supplier_id = s.supplier_id
LEFT JOIN receipt_stats r
  ON r.supplier_id = s.supplier_id;


CREATE OR REPLACE VIEW decision_ops.v_case_workbench
WITH (security_invoker = true) AS
SELECT
    c.case_id,
    c.decision_type,
    c.entity_key,
    c.branch_id,
    b.branch_code,
    b.display_name AS branch_name,
    b.governorate,
    b.representative_city,
    c.product_id,
    p.trade_name_en,
    p.trade_name_ar,
    p.scientific_name,
    p.manufacturer,
    c.batch_id,
    sb.batch_code,
    sb.expiry_date,
    sb.quantity_on_hand AS batch_quantity_on_hand,
    c.status,
    c.severity,
    c.action_required,
    c.recommended_units,
    c.latest_prediction_event_id,
    c.source_mode,
    c.approval_required,
    c.auto_execution_allowed,
    c.resolution_code,
    c.opened_at,
    c.acknowledged_at,
    c.decided_at,
    c.closed_at,
    c.updated_at,
    e.model_key,
    e.model_version,
    e.probability,
    e.threshold,
    e.observed_at AS evidence_observed_at,
    d.draft_id,
    d.draft_status,
    d.supplier_selected,
    d.automatic_po_allowed,
    d.approved_by,
    d.approved_at,

    CASE
        WHEN b.provenance_class IS NOT NULL
         AND sb.provenance_class IS NOT NULL
         AND b.provenance_class <> sb.provenance_class
            THEN 'MIXED_OPERATIONAL'
        ELSE COALESCE(
            sb.provenance_class,
            b.provenance_class
        )
    END AS operational_provenance_class,

    p.provenance_class AS reference_provenance_class

FROM decision_ops.decision_case c
LEFT JOIN master.pharmacy_branch b
  ON b.branch_id = c.branch_id
LEFT JOIN master.product p
  ON p.product_id = c.product_id
LEFT JOIN inventory.stock_batch sb
  ON sb.batch_id = c.batch_id
LEFT JOIN LATERAL (
    SELECT
        de.model_key,
        de.model_version,
        de.probability,
        de.threshold,
        de.observed_at
    FROM decision_ops.decision_evidence de
    WHERE de.case_id = c.case_id
    ORDER BY
        de.observed_at DESC,
        de.prediction_event_id DESC
    LIMIT 1
) e ON true
LEFT JOIN decision_ops.replenishment_draft d
  ON d.case_id = c.case_id;


-- Narrow column-level grants required because v_case_workbench
-- deliberately remains security_invoker = true.
GRANT SELECT (provenance_class)
ON master.pharmacy_branch
TO pharmstock_workbench;

GRANT SELECT (provenance_class)
ON master.product
TO pharmstock_workbench;

GRANT SELECT (provenance_class)
ON inventory.stock_batch
TO pharmstock_workbench;


GRANT SELECT
ON assistant_api.v_inventory_context
TO pharmstock_workbench;

GRANT SELECT
ON assistant_api.v_ml_signal
TO pharmstock_workbench;

GRANT SELECT
ON assistant_api.v_supplier_context
TO pharmstock_workbench;

GRANT SELECT
ON decision_ops.v_case_workbench
TO pharmstock_workbench;
