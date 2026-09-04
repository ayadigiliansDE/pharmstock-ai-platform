\set ON_ERROR_STOP on

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pharmstock_decision') THEN
        CREATE ROLE pharmstock_decision LOGIN;
    END IF;
END
$$;

SELECT format('ALTER ROLE pharmstock_decision WITH LOGIN PASSWORD %L', :'decision_password')
\gexec

GRANT CONNECT ON DATABASE pharmstock_ops TO pharmstock_decision;

CREATE SCHEMA IF NOT EXISTS decision_ops;

CREATE TABLE IF NOT EXISTS decision_ops.ml_event_inbox (
    prediction_event_id text PRIMARY KEY REFERENCES mlops.prediction_event(prediction_event_id),
    topic text NOT NULL,
    partition_id integer NOT NULL,
    offset_value bigint NOT NULL,
    model_key text NOT NULL,
    entity_key text NOT NULL,
    payload jsonb NOT NULL,
    outcome text NOT NULL
        CHECK (outcome IN (
            'PROCESSED', 'IGNORED_SMOKE', 'IGNORED_NON_ACTIONABLE', 'ALREADY_APPLIED'
        )),
    received_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (topic, partition_id, offset_value)
);

CREATE TABLE IF NOT EXISTS decision_ops.ml_event_quarantine (
    workflow_event_hash text PRIMARY KEY,
    topic text NOT NULL,
    partition_id integer NOT NULL,
    offset_value bigint NOT NULL,
    raw_payload text,
    error_class text NOT NULL,
    error_message text NOT NULL,
    quarantined_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (topic, partition_id, offset_value)
);

CREATE INDEX IF NOT EXISTS idx_stage7l_quarantine_time
    ON decision_ops.ml_event_quarantine (quarantined_at DESC);

CREATE TABLE IF NOT EXISTS decision_ops.decision_case (
    case_id uuid PRIMARY KEY,
    decision_type text NOT NULL CHECK (decision_type IN ('STOCKOUT', 'REORDER', 'EXPIRY')),
    entity_key text NOT NULL,
    branch_id uuid REFERENCES master.pharmacy_branch(branch_id),
    product_id uuid REFERENCES master.product(product_id),
    batch_id uuid REFERENCES inventory.stock_batch(batch_id),
    status text NOT NULL DEFAULT 'OPEN'
        CHECK (status IN ('OPEN', 'ACKNOWLEDGED', 'APPROVED_DRAFT', 'REJECTED', 'CLOSED')),
    severity text NOT NULL DEFAULT 'NORMAL'
        CHECK (severity IN ('NORMAL', 'WATCH', 'MEDIUM', 'HIGH', 'CRITICAL')),
    action_required boolean NOT NULL,
    recommended_units integer CHECK (recommended_units IS NULL OR recommended_units > 0),
    latest_prediction_event_id text NOT NULL
        REFERENCES mlops.prediction_event(prediction_event_id),
    source_mode text NOT NULL CHECK (source_mode IN ('BOOTSTRAP', 'KAFKA')),
    approval_required boolean NOT NULL DEFAULT true CHECK (approval_required),
    auto_execution_allowed boolean NOT NULL DEFAULT false CHECK (NOT auto_execution_allowed),
    resolution_code text,
    opened_at timestamptz NOT NULL DEFAULT now(),
    acknowledged_at timestamptz,
    decided_at timestamptz,
    closed_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_stage7l_active_case
    ON decision_ops.decision_case (decision_type, entity_key)
    WHERE status IN ('OPEN', 'ACKNOWLEDGED', 'APPROVED_DRAFT');

CREATE INDEX IF NOT EXISTS idx_stage7l_case_queue
    ON decision_ops.decision_case (status, severity, updated_at DESC);

CREATE TABLE IF NOT EXISTS decision_ops.decision_evidence (
    prediction_event_id text PRIMARY KEY REFERENCES mlops.prediction_event(prediction_event_id),
    case_id uuid NOT NULL REFERENCES decision_ops.decision_case(case_id) ON DELETE CASCADE,
    model_key text NOT NULL,
    model_version text NOT NULL,
    severity text NOT NULL,
    action_required boolean NOT NULL,
    recommended_units integer,
    probability numeric(18,12),
    threshold numeric(18,12),
    payload jsonb NOT NULL,
    observed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decision_ops.replenishment_draft (
    draft_id uuid PRIMARY KEY,
    case_id uuid NOT NULL UNIQUE REFERENCES decision_ops.decision_case(case_id) ON DELETE CASCADE,
    branch_id uuid NOT NULL REFERENCES master.pharmacy_branch(branch_id),
    product_id uuid NOT NULL REFERENCES master.product(product_id),
    recommended_units integer NOT NULL CHECK (recommended_units > 0),
    draft_status text NOT NULL DEFAULT 'PENDING_REVIEW'
        CHECK (draft_status IN ('PENDING_REVIEW', 'APPROVED', 'REJECTED', 'CLOSED')),
    supplier_selected boolean NOT NULL DEFAULT false CHECK (NOT supplier_selected),
    automatic_po_allowed boolean NOT NULL DEFAULT false CHECK (NOT automatic_po_allowed),
    approved_by text,
    approved_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decision_ops.decision_audit (
    audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    case_id uuid NOT NULL REFERENCES decision_ops.decision_case(case_id) ON DELETE CASCADE,
    action text NOT NULL,
    from_status text,
    to_status text NOT NULL,
    actor_type text NOT NULL CHECK (actor_type IN ('SYSTEM', 'HUMAN')),
    actor_id text NOT NULL,
    note text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_stage7l_audit_case_time
    ON decision_ops.decision_audit (case_id, created_at DESC);

GRANT USAGE ON SCHEMA decision_ops, mlops TO pharmstock_decision;
GRANT SELECT ON mlops.prediction_event TO pharmstock_decision;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA decision_ops TO pharmstock_decision;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA decision_ops TO pharmstock_decision;
ALTER DEFAULT PRIVILEGES IN SCHEMA decision_ops
    GRANT SELECT, INSERT, UPDATE ON TABLES TO pharmstock_decision;
ALTER DEFAULT PRIVILEGES IN SCHEMA decision_ops
    GRANT USAGE, SELECT ON SEQUENCES TO pharmstock_decision;

-- Stage 7L must never have procurement execution privileges.
REVOKE INSERT, UPDATE, DELETE ON procurement.purchase_order FROM pharmstock_decision;
REVOKE INSERT, UPDATE, DELETE ON procurement.purchase_order_line FROM pharmstock_decision;
REVOKE INSERT, UPDATE, DELETE ON procurement.goods_receipt FROM pharmstock_decision;
REVOKE INSERT, UPDATE, DELETE ON procurement.goods_receipt_line FROM pharmstock_decision;

-- Decision workflow state must not feed the operational CDC publication.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_publication_tables
        WHERE pubname = 'pharmstock_cdc_publication'
          AND schemaname = 'decision_ops'
    ) THEN
        RAISE EXCEPTION 'decision_ops schema must not be part of pharmstock_cdc_publication';
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_stage7l_prediction_bootstrap
    ON mlops.prediction_event (model_key, entity_key, created_at DESC)
    WHERE model_key IN ('stockout_risk', 'reorder_recommendation', 'expiry_slow_moving_risk');
