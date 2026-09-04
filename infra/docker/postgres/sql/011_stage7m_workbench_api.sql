\set ON_ERROR_STOP on

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pharmstock_workbench') THEN
        CREATE ROLE pharmstock_workbench LOGIN;
    END IF;
END
$$;

SELECT format('ALTER ROLE pharmstock_workbench WITH LOGIN PASSWORD %L', :'workbench_password')
\gexec

GRANT CONNECT ON DATABASE pharmstock_ops TO pharmstock_workbench;
GRANT USAGE ON SCHEMA decision_ops, master, inventory TO pharmstock_workbench;

CREATE OR REPLACE VIEW decision_ops.v_case_workbench
WITH (security_invoker = true)
AS
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
    d.approved_at
FROM decision_ops.decision_case c
LEFT JOIN master.pharmacy_branch b ON b.branch_id = c.branch_id
LEFT JOIN master.product p ON p.product_id = c.product_id
LEFT JOIN inventory.stock_batch sb ON sb.batch_id = c.batch_id
LEFT JOIN LATERAL (
    SELECT de.model_key, de.model_version, de.probability, de.threshold, de.observed_at
    FROM decision_ops.decision_evidence de
    WHERE de.case_id = c.case_id
    ORDER BY de.observed_at DESC, de.prediction_event_id DESC
    LIMIT 1
) e ON true
LEFT JOIN decision_ops.replenishment_draft d ON d.case_id = c.case_id;

GRANT SELECT ON decision_ops.decision_case TO pharmstock_workbench;
GRANT SELECT ON decision_ops.decision_evidence TO pharmstock_workbench;
GRANT SELECT ON decision_ops.replenishment_draft TO pharmstock_workbench;
GRANT SELECT ON decision_ops.decision_audit TO pharmstock_workbench;
GRANT SELECT ON decision_ops.v_case_workbench TO pharmstock_workbench;
GRANT UPDATE (
    status, acknowledged_at, decided_at, closed_at, resolution_code, updated_at
) ON decision_ops.decision_case TO pharmstock_workbench;
GRANT UPDATE (
    draft_status, approved_by, approved_at, updated_at
) ON decision_ops.replenishment_draft TO pharmstock_workbench;
GRANT INSERT ON decision_ops.decision_audit TO pharmstock_workbench;
GRANT USAGE, SELECT ON SEQUENCE decision_ops.decision_audit_audit_id_seq
    TO pharmstock_workbench;

GRANT SELECT (
    branch_id, branch_code, display_name, governorate, representative_city
) ON master.pharmacy_branch TO pharmstock_workbench;
GRANT SELECT (
    product_id, trade_name_en, trade_name_ar, scientific_name, manufacturer
) ON master.product TO pharmstock_workbench;
GRANT SELECT (
    batch_id, batch_code, expiry_date, quantity_on_hand
) ON inventory.stock_batch TO pharmstock_workbench;

-- Audit history is append-only for operational roles.
REVOKE UPDATE, DELETE ON decision_ops.decision_audit FROM pharmstock_decision;
REVOKE UPDATE, DELETE ON decision_ops.decision_audit FROM pharmstock_workbench;

-- Workbench can change only governed workflow state. It cannot create/delete cases.
REVOKE INSERT, DELETE ON decision_ops.decision_case FROM pharmstock_workbench;
REVOKE INSERT, DELETE ON decision_ops.replenishment_draft FROM pharmstock_workbench;
REVOKE INSERT, UPDATE, DELETE ON decision_ops.decision_evidence FROM pharmstock_workbench;
REVOKE INSERT, UPDATE, DELETE ON decision_ops.ml_event_inbox FROM pharmstock_workbench;
REVOKE INSERT, UPDATE, DELETE ON decision_ops.ml_event_quarantine FROM pharmstock_workbench;

-- Stage 7M must never have procurement execution privileges.
REVOKE INSERT, UPDATE, DELETE ON procurement.purchase_order FROM pharmstock_workbench;
REVOKE INSERT, UPDATE, DELETE ON procurement.purchase_order_line FROM pharmstock_workbench;
REVOKE INSERT, UPDATE, DELETE ON procurement.goods_receipt FROM pharmstock_workbench;
REVOKE INSERT, UPDATE, DELETE ON procurement.goods_receipt_line FROM pharmstock_workbench;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_publication_tables
        WHERE pubname = 'pharmstock_cdc_publication'
          AND schemaname = 'decision_ops'
    ) THEN
        RAISE EXCEPTION 'decision_ops must remain outside pharmstock_cdc_publication';
    END IF;
END
$$;
