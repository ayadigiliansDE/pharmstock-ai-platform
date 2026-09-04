\set ON_ERROR_STOP on

CREATE SCHEMA IF NOT EXISTS mlops;

CREATE TABLE IF NOT EXISTS mlops.online_source_event (
    source_event_id text PRIMARY KEY,
    topic text NOT NULL,
    partition_id integer NOT NULL,
    offset_value bigint NOT NULL,
    source_schema text NOT NULL,
    source_table text NOT NULL,
    source_operation char(1) NOT NULL CHECK (source_operation IN ('c', 'u', 'd', 'r', 's')),
    source_event_ts timestamptz,
    affected_key_count integer NOT NULL DEFAULT 0 CHECK (affected_key_count >= 0),
    processed_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (topic, partition_id, offset_value)
);

CREATE TABLE IF NOT EXISTS mlops.prediction_event (
    prediction_event_id text PRIMARY KEY,
    source_event_id text NOT NULL REFERENCES mlops.online_source_event(source_event_id),
    model_key text NOT NULL,
    model_version text NOT NULL,
    entity_type text NOT NULL CHECK (entity_type IN ('PRODUCT', 'BRANCH_PRODUCT', 'BATCH', 'MODEL')),
    entity_key text NOT NULL,
    output_topic text NOT NULL,
    kafka_key text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_event_id, model_key, entity_type, entity_key)
);

CREATE TABLE IF NOT EXISTS mlops.prediction_outbox (
    prediction_event_id text PRIMARY KEY REFERENCES mlops.prediction_event(prediction_event_id)
        ON DELETE CASCADE,
    output_topic text NOT NULL,
    kafka_key text NOT NULL,
    payload jsonb NOT NULL,
    publish_attempts integer NOT NULL DEFAULT 0 CHECK (publish_attempts >= 0),
    published_at timestamptz,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_prediction_outbox_pending
    ON mlops.prediction_outbox (created_at)
    WHERE published_at IS NULL;

CREATE TABLE IF NOT EXISTS mlops.online_source_quarantine (
    source_event_id text PRIMARY KEY,
    topic text NOT NULL,
    partition_id integer NOT NULL,
    offset_value bigint NOT NULL,
    raw_payload text,
    error_class text NOT NULL,
    error_message text NOT NULL,
    quarantined_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (topic, partition_id, offset_value)
);

CREATE INDEX IF NOT EXISTS idx_online_source_quarantine_time
    ON mlops.online_source_quarantine (quarantined_at DESC);

CREATE TABLE IF NOT EXISTS mlops.latest_demand_forecast (
    product_id uuid PRIMARY KEY REFERENCES master.product(product_id),
    model_version text NOT NULL,
    feature_as_of_date date NOT NULL,
    demand_1d numeric(18,6) NOT NULL CHECK (demand_1d >= 0),
    demand_7d numeric(18,6) NOT NULL CHECK (demand_7d >= 0),
    demand_14d numeric(18,6) NOT NULL CHECK (demand_14d >= 0),
    demand_30d numeric(18,6) NOT NULL CHECK (demand_30d >= 0),
    source_event_id text NOT NULL REFERENCES mlops.online_source_event(source_event_id),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mlops.latest_branch_product_decision (
    branch_id uuid NOT NULL REFERENCES master.pharmacy_branch(branch_id),
    product_id uuid NOT NULL REFERENCES master.product(product_id),
    model_key text NOT NULL CHECK (model_key IN ('stockout_risk', 'reorder_recommendation')),
    model_version text NOT NULL,
    feature_as_of_date date NOT NULL,
    prediction_value numeric(18,8) NOT NULL,
    probability numeric(18,12),
    threshold numeric(18,12),
    action_required boolean NOT NULL DEFAULT false,
    severity text NOT NULL DEFAULT 'NORMAL'
        CHECK (severity IN ('NORMAL', 'WATCH', 'MEDIUM', 'HIGH', 'CRITICAL')),
    source_event_id text NOT NULL REFERENCES mlops.online_source_event(source_event_id),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (branch_id, product_id, model_key)
);

CREATE INDEX IF NOT EXISTS idx_latest_branch_product_action
    ON mlops.latest_branch_product_decision (action_required, severity, updated_at DESC);

CREATE TABLE IF NOT EXISTS mlops.latest_expiry_risk (
    batch_id uuid PRIMARY KEY REFERENCES inventory.stock_batch(batch_id),
    branch_id uuid NOT NULL REFERENCES master.pharmacy_branch(branch_id),
    product_id uuid NOT NULL REFERENCES master.product(product_id),
    model_version text NOT NULL,
    feature_as_of_date date NOT NULL,
    probability numeric(18,12) NOT NULL CHECK (probability BETWEEN 0 AND 1),
    threshold numeric(18,12) NOT NULL CHECK (threshold BETWEEN 0 AND 1),
    high_risk boolean NOT NULL,
    days_to_expiry integer NOT NULL,
    quantity_on_hand integer NOT NULL CHECK (quantity_on_hand >= 0),
    source_event_id text NOT NULL REFERENCES mlops.online_source_event(source_event_id),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_latest_expiry_high_risk
    ON mlops.latest_expiry_risk (high_risk, days_to_expiry, updated_at DESC);

CREATE TABLE IF NOT EXISTS mlops.alert_state (
    branch_id uuid NOT NULL REFERENCES master.pharmacy_branch(branch_id),
    product_id uuid NOT NULL REFERENCES master.product(product_id),
    alert_type text NOT NULL CHECK (alert_type = 'stockout_risk'),
    last_severity text NOT NULL DEFAULT 'NORMAL'
        CHECK (last_severity IN ('NORMAL', 'WATCH', 'MEDIUM', 'HIGH', 'CRITICAL')),
    last_probability numeric(18,12),
    last_alert_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (branch_id, product_id, alert_type)
);

-- The ML operational store must never feed predictions back into Debezium source topics.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_publication_tables
        WHERE pubname = 'pharmstock_cdc_publication'
          AND schemaname = 'mlops'
    ) THEN
        RAISE EXCEPTION 'mlops schema must not be part of pharmstock_cdc_publication';
    END IF;
END
$$;
