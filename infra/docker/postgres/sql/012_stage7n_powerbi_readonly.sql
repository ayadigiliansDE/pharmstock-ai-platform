\set ON_ERROR_STOP on

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pharmstock_bi') THEN
        CREATE ROLE pharmstock_bi LOGIN;
    END IF;
END
$$;

SELECT format('ALTER ROLE pharmstock_bi WITH LOGIN PASSWORD %L', :'bi_password')
\gexec

GRANT CONNECT ON DATABASE pharmstock_ops TO pharmstock_bi;
CREATE SCHEMA IF NOT EXISTS bi;

CREATE OR REPLACE VIEW bi.v_ml_demand_forecast
WITH (security_invoker = false)
AS
SELECT
    f.product_id,
    p.trade_name_en,
    p.trade_name_ar,
    p.scientific_name,
    p.manufacturer,
    f.model_version,
    f.feature_as_of_date,
    f.demand_1d,
    f.demand_7d,
    f.demand_14d,
    f.demand_30d,
    f.updated_at
FROM mlops.latest_demand_forecast f
JOIN mlops.online_source_event ose USING (source_event_id)
JOIN master.product p USING (product_id)
WHERE ose.source_table <> 'acceptance_smoke';

CREATE OR REPLACE VIEW bi.v_ml_branch_product_decision
WITH (security_invoker = false)
AS
SELECT
    d.branch_id,
    b.branch_code,
    b.display_name AS branch_name,
    b.governorate,
    b.representative_city,
    d.product_id,
    p.trade_name_en,
    p.trade_name_ar,
    p.scientific_name,
    p.manufacturer,
    d.model_key,
    d.model_version,
    d.feature_as_of_date,
    d.prediction_value,
    d.probability,
    d.threshold,
    d.action_required,
    d.severity,
    d.updated_at
FROM mlops.latest_branch_product_decision d
JOIN mlops.online_source_event ose USING (source_event_id)
JOIN master.pharmacy_branch b USING (branch_id)
JOIN master.product p USING (product_id)
WHERE ose.source_table <> 'acceptance_smoke';

CREATE OR REPLACE VIEW bi.v_ml_expiry_risk
WITH (security_invoker = false)
AS
SELECT
    r.batch_id,
    sb.batch_code,
    r.branch_id,
    b.branch_code,
    b.display_name AS branch_name,
    b.governorate,
    r.product_id,
    p.trade_name_en,
    p.scientific_name,
    p.manufacturer,
    r.model_version,
    r.feature_as_of_date,
    r.probability,
    r.threshold,
    r.high_risk,
    r.days_to_expiry,
    r.quantity_on_hand,
    r.updated_at
FROM mlops.latest_expiry_risk r
JOIN mlops.online_source_event ose
    ON ose.source_event_id = r.source_event_id
JOIN inventory.stock_batch sb
    ON sb.batch_id = r.batch_id
   AND sb.branch_id = r.branch_id
   AND sb.product_id = r.product_id
JOIN master.pharmacy_branch b
    ON b.branch_id = r.branch_id
JOIN master.product p
    ON p.product_id = r.product_id
WHERE ose.source_table <> 'acceptance_smoke';

CREATE OR REPLACE VIEW bi.v_decision_case
WITH (security_invoker = false)
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
    d.approved_at,
    GREATEST(EXTRACT(EPOCH FROM (now() - c.opened_at)) / 3600.0, 0) AS case_age_hours
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
    ORDER BY de.observed_at DESC, de.prediction_event_id DESC
    LIMIT 1
) e ON true
LEFT JOIN decision_ops.replenishment_draft d
    ON d.case_id = c.case_id;

CREATE OR REPLACE VIEW bi.v_decision_audit
WITH (security_invoker = false)
AS
SELECT
    a.audit_id,
    a.case_id,
    c.decision_type,
    c.branch_id,
    c.product_id,
    c.severity,
    a.action,
    a.from_status,
    a.to_status,
    a.actor_type,
    a.actor_id,
    a.note,
    a.created_at
FROM decision_ops.decision_audit a
JOIN decision_ops.decision_case c USING (case_id);

-- Pin ownership explicitly so every curated BI view executes against the
-- administrator-owned read model rather than inheriting an accidental owner.
ALTER VIEW bi.v_ml_demand_forecast OWNER TO pharmstock_admin;
ALTER VIEW bi.v_ml_branch_product_decision OWNER TO pharmstock_admin;
ALTER VIEW bi.v_ml_expiry_risk OWNER TO pharmstock_admin;
ALTER VIEW bi.v_decision_case OWNER TO pharmstock_admin;
ALTER VIEW bi.v_decision_audit OWNER TO pharmstock_admin;

-- Power BI can read only the curated BI views. The views are owned by the
-- administrator and intentionally do not expose arbitrary underlying tables.
GRANT USAGE ON SCHEMA bi TO pharmstock_bi;
GRANT SELECT ON ALL TABLES IN SCHEMA bi TO pharmstock_bi;
REVOKE USAGE ON SCHEMA mlops, master, inventory, decision_ops, procurement FROM pharmstock_bi;

-- Explicitly revoke all write paths, including the semantic schema itself.
REVOKE CREATE ON SCHEMA bi FROM pharmstock_bi;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA bi FROM pharmstock_bi;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA mlops FROM pharmstock_bi;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA decision_ops FROM pharmstock_bi;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA inventory FROM pharmstock_bi;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA master FROM pharmstock_bi;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA procurement FROM pharmstock_bi;

DO $$
DECLARE
    can_write boolean;
BEGIN
    SELECT
        has_table_privilege('pharmstock_bi', 'procurement.purchase_order', 'INSERT')
        OR has_table_privilege('pharmstock_bi', 'procurement.purchase_order', 'UPDATE')
        OR has_table_privilege('pharmstock_bi', 'procurement.purchase_order', 'DELETE')
        OR has_table_privilege('pharmstock_bi', 'decision_ops.decision_case', 'UPDATE')
        OR has_table_privilege('pharmstock_bi', 'mlops.prediction_event', 'INSERT')
    INTO can_write;
    IF can_write THEN
        RAISE EXCEPTION 'pharmstock_bi must remain read-only';
    END IF;
END
$$;
