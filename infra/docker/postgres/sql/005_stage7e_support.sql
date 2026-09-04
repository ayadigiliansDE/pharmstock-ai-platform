\set ON_ERROR_STOP on

CREATE TABLE IF NOT EXISTS audit.simulation_run (
    run_token text PRIMARY KEY,
    stage text NOT NULL CHECK (stage = '7E'),
    profile text NOT NULL,
    model_version text NOT NULL,
    provenance_class text NOT NULL CHECK (provenance_class = 'SYNTHETIC_CALIBRATED'),
    seed bigint NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    branch_limit integer NOT NULL CHECK (branch_limit > 0),
    base_transactions_per_branch_day integer NOT NULL
        CHECK (base_transactions_per_branch_day > 0),
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    status text NOT NULL CHECK (status IN ('RUNNING', 'PASS', 'FAIL')),
    generated_counts jsonb NOT NULL DEFAULT '{}'::jsonb,
    notes text,
    CHECK (end_date >= start_date)
);

CREATE OR REPLACE FUNCTION audit.hash_unit(input_text text)
RETURNS double precision
LANGUAGE sql
IMMUTABLE
STRICT
PARALLEL SAFE
AS $$
    SELECT ((('x' || substr(md5(input_text), 1, 8))::bit(32)::bigint)::double precision)
           / 4294967295.0;
$$;

CREATE OR REPLACE FUNCTION audit.stage7e_receipt_delay_days(input_text text)
RETURNS integer
LANGUAGE sql
IMMUTABLE
STRICT
PARALLEL SAFE
AS $$
    SELECT CASE
        WHEN audit.hash_unit(input_text) < 0.78 THEN 0
        WHEN audit.hash_unit(input_text) < 0.90 THEN 1
        WHEN audit.hash_unit(input_text) < 0.97 THEN 2
        ELSE 3 + LEAST(2, floor(3 * audit.hash_unit(input_text || '|tail'))::integer)
    END;
$$;

CREATE TABLE IF NOT EXISTS pos.demand_attempt (
    demand_attempt_id uuid PRIMARY KEY,
    branch_id uuid NOT NULL REFERENCES master.pharmacy_branch(branch_id),
    transaction_ts timestamptz NOT NULL,
    product_id uuid NOT NULL REFERENCES master.product(product_id),
    requested_units integer NOT NULL CHECK (requested_units > 0),
    fulfilled_units integer NOT NULL CHECK (fulfilled_units >= 0),
    lost_units integer NOT NULL CHECK (lost_units >= 0),
    outcome text NOT NULL CHECK (outcome IN ('FULFILLED', 'PARTIAL', 'OUT_OF_STOCK')),
    reason_code text NOT NULL,
    linked_sale_id uuid REFERENCES pos.sale_header(sale_id),
    correlation_id uuid NOT NULL,
    provenance_class text NOT NULL CHECK (provenance_class = 'SYNTHETIC_CALIBRATED'),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (requested_units = fulfilled_units + lost_units)
);

CREATE INDEX IF NOT EXISTS idx_demand_attempt_branch_time
    ON pos.demand_attempt (branch_id, transaction_ts);
CREATE INDEX IF NOT EXISTS idx_demand_attempt_product_time
    ON pos.demand_attempt (product_id, transaction_ts);

-- Stage 7K.5 prerequisite: demand_attempt carries fulfilled + partial + lost demand.
-- Stage 7D cannot publish it because the table does not exist until Stage 7E.
-- Extend the existing logical publication without snapshotting historical rows.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_publication WHERE pubname = 'pharmstock_cdc_publication'
    ) AND NOT EXISTS (
        SELECT 1
        FROM pg_publication_tables
        WHERE pubname = 'pharmstock_cdc_publication'
          AND schemaname = 'pos'
          AND tablename = 'demand_attempt'
    ) THEN
        ALTER PUBLICATION pharmstock_cdc_publication ADD TABLE pos.demand_attempt;
    END IF;
END
$$;

CREATE UNLOGGED TABLE IF NOT EXISTS staging.stage7e_product_pool (
    product_rn integer PRIMARY KEY,
    product_id uuid NOT NULL UNIQUE,
    retail_price_egp numeric(14,2) NOT NULL,
    purchase_cost_egp numeric(14,2) NOT NULL,
    tax_treatment text NOT NULL
);

CREATE UNLOGGED TABLE IF NOT EXISTS staging.stage7e_sale_seed (
    sale_id uuid PRIMARY KEY,
    branch_id uuid NOT NULL,
    branch_code text NOT NULL,
    terminal_id uuid NOT NULL,
    transaction_number text NOT NULL,
    transaction_ts timestamptz NOT NULL,
    channel text NOT NULL,
    correlation_id uuid NOT NULL,
    payment_method text NOT NULL,
    line_count integer NOT NULL CHECK (line_count BETWEEN 1 AND 4)
);

CREATE INDEX IF NOT EXISTS idx_stage7e_sale_seed_branch_time
    ON staging.stage7e_sale_seed (branch_id, transaction_ts);

CREATE UNLOGGED TABLE IF NOT EXISTS staging.stage7e_sale_line_seed (
    sale_line_id uuid PRIMARY KEY,
    sale_id uuid NOT NULL,
    branch_id uuid NOT NULL,
    transaction_ts timestamptz NOT NULL,
    line_number integer NOT NULL,
    product_id uuid NOT NULL,
    batch_id uuid,
    quantity integer NOT NULL,
    retail_unit_price_egp numeric(14,2) NOT NULL,
    discount_pct numeric(10,6) NOT NULL,
    selling_unit_price_egp numeric(14,2) NOT NULL,
    gross_sales_egp numeric(16,2) NOT NULL,
    discount_amount_egp numeric(16,2) NOT NULL,
    net_sales_egp numeric(16,2) NOT NULL,
    purchase_cost_egp numeric(14,2) NOT NULL,
    cogs_egp numeric(16,2) NOT NULL,
    gross_profit_egp numeric(16,2) NOT NULL,
    gross_margin_pct numeric(10,6) NOT NULL,
    tax_treatment text NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_stage7e_line_seed_sale
    ON staging.stage7e_sale_line_seed (sale_id, line_number);
CREATE INDEX IF NOT EXISTS idx_stage7e_line_seed_branch_product
    ON staging.stage7e_sale_line_seed (branch_id, product_id, transaction_ts);

-- Stage 7E v0.26.1: privacy-safe customer digital twin + fast resumable audit.
CREATE SCHEMA IF NOT EXISTS customer;

ALTER TABLE audit.simulation_run
    ADD COLUMN IF NOT EXISTS baseline_database_size_bytes bigint;

CREATE TABLE IF NOT EXISTS audit.stage7e_run_metric (
    run_token text NOT NULL REFERENCES audit.simulation_run(run_token) ON DELETE CASCADE,
    metric_name text NOT NULL,
    metric_value_numeric numeric,
    metric_value_text text,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_token, metric_name),
    CHECK (metric_value_numeric IS NOT NULL OR metric_value_text IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS customer.household (
    household_id uuid PRIMARY KEY,
    household_key text NOT NULL UNIQUE,
    preferred_branch_id uuid NOT NULL REFERENCES master.pharmacy_branch(branch_id),
    governorate_code text NOT NULL,
    locality_type text NOT NULL CHECK (locality_type IN ('urban', 'rural')),
    household_size integer NOT NULL CHECK (household_size BETWEEN 1 AND 6),
    household_segment text NOT NULL,
    provenance_class text NOT NULL CHECK (provenance_class = 'SYNTHETIC_CALIBRATED'),
    synthetic_record boolean NOT NULL DEFAULT true CHECK (synthetic_record),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_customer_household_branch
    ON customer.household (preferred_branch_id);

CREATE TABLE IF NOT EXISTS customer.customer_profile (
    customer_id uuid PRIMARY KEY,
    customer_key text NOT NULL UNIQUE,
    household_id uuid NOT NULL REFERENCES customer.household(household_id),
    preferred_branch_id uuid NOT NULL REFERENCES master.pharmacy_branch(branch_id),
    branch_customer_seq integer NOT NULL CHECK (branch_customer_seq BETWEEN 1 AND 50),
    customer_segment text NOT NULL CHECK (
        customer_segment IN (
            'CHRONIC_REPEAT',
            'FAMILY_CAREGIVER',
            'OTC_CONVENIENCE',
            'PRICE_SENSITIVE',
            'DIGITAL_FIRST'
        )
    ),
    age_band text NOT NULL,
    gender_marker text NOT NULL CHECK (gender_marker IN ('FEMALE', 'MALE', 'UNSPECIFIED')),
    governorate_code text NOT NULL,
    locality_type text NOT NULL CHECK (locality_type IN ('urban', 'rural')),
    loyalty_tier text NOT NULL CHECK (loyalty_tier IN ('NONE', 'BRONZE', 'SILVER', 'GOLD')),
    join_date date NOT NULL,
    purchase_frequency_per_30d numeric(8,4) NOT NULL CHECK (purchase_frequency_per_30d > 0),
    average_basket_size numeric(8,4) NOT NULL CHECK (average_basket_size > 0),
    discount_sensitivity numeric(10,6) NOT NULL CHECK (discount_sensitivity BETWEEN 0 AND 1),
    brand_loyalty_score numeric(10,6) NOT NULL CHECK (brand_loyalty_score BETWEEN 0 AND 1),
    generic_substitution_tendency numeric(10,6) NOT NULL
        CHECK (generic_substitution_tendency BETWEEN 0 AND 1),
    preferred_payment_method text NOT NULL
        CHECK (preferred_payment_method IN ('CASH', 'CARD', 'DIGITAL_WALLET', 'THIRD_PARTY_PAYER')),
    delivery_preference numeric(10,6) NOT NULL CHECK (delivery_preference BETWEEN 0 AND 1),
    prescription_purchase_ratio numeric(10,6) NOT NULL
        CHECK (prescription_purchase_ratio BETWEEN 0 AND 1),
    otc_purchase_ratio numeric(10,6) NOT NULL CHECK (otc_purchase_ratio BETWEEN 0 AND 1),
    chronic_repeat_purchase_pattern boolean NOT NULL,
    last_purchase_at timestamptz,
    provenance_class text NOT NULL CHECK (provenance_class = 'SYNTHETIC_CALIBRATED'),
    synthetic_record boolean NOT NULL DEFAULT true CHECK (synthetic_record),
    direct_identifiers_generated boolean NOT NULL DEFAULT false
        CHECK (direct_identifiers_generated = false),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (preferred_branch_id, branch_customer_seq),
    CHECK (abs(prescription_purchase_ratio + otc_purchase_ratio - 1) <= 0.001)
);

CREATE INDEX IF NOT EXISTS idx_customer_profile_household
    ON customer.customer_profile (household_id);
CREATE INDEX IF NOT EXISTS idx_customer_profile_branch_segment
    ON customer.customer_profile (preferred_branch_id, customer_segment);

CREATE TABLE IF NOT EXISTS customer.loyalty_account (
    loyalty_account_id uuid PRIMARY KEY,
    customer_id uuid NOT NULL UNIQUE REFERENCES customer.customer_profile(customer_id),
    loyalty_id text NOT NULL UNIQUE,
    loyalty_tier text NOT NULL CHECK (loyalty_tier IN ('BRONZE', 'SILVER', 'GOLD')),
    points_balance integer NOT NULL CHECK (points_balance >= 0),
    joined_at date NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    provenance_class text NOT NULL CHECK (provenance_class = 'SYNTHETIC_CALIBRATED'),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS customer.patient_profile (
    patient_id uuid PRIMARY KEY,
    patient_key text NOT NULL UNIQUE,
    household_id uuid NOT NULL REFERENCES customer.household(household_id),
    household_patient_seq integer NOT NULL CHECK (household_patient_seq BETWEEN 1 AND 3),
    age_band text NOT NULL,
    sex_marker text NOT NULL CHECK (sex_marker IN ('FEMALE', 'MALE', 'UNSPECIFIED')),
    relationship_group text NOT NULL
        CHECK (relationship_group IN ('SELF', 'CHILD', 'ADULT_HOUSEHOLD_MEMBER')),
    chronic_profile_band text NOT NULL
        CHECK (chronic_profile_band IN ('NONE', 'LOW', 'MODERATE', 'HIGH')),
    provenance_class text NOT NULL CHECK (provenance_class = 'SYNTHETIC_CALIBRATED'),
    synthetic_record boolean NOT NULL DEFAULT true CHECK (synthetic_record),
    direct_identifiers_generated boolean NOT NULL DEFAULT false
        CHECK (direct_identifiers_generated = false),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (household_id, household_patient_seq)
);

ALTER TABLE pos.sale_header
    ADD COLUMN IF NOT EXISTS simulation_run_token text;
ALTER TABLE pos.sale_header
    ADD COLUMN IF NOT EXISTS customer_id uuid REFERENCES customer.customer_profile(customer_id);
ALTER TABLE pos.sale_header
    ADD COLUMN IF NOT EXISTS loyalty_account_id uuid REFERENCES customer.loyalty_account(loyalty_account_id);
ALTER TABLE pos.sale_header
    ADD COLUMN IF NOT EXISTS customer_mode text;
ALTER TABLE pos.sale_header
    ADD COLUMN IF NOT EXISTS anonymous_customer_key text;
ALTER TABLE pos.sale_header
    ADD COLUMN IF NOT EXISTS prescription_flag boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_sale_header_simulation_run
    ON pos.sale_header (simulation_run_token);
CREATE INDEX IF NOT EXISTS idx_sale_header_customer_time
    ON pos.sale_header (customer_id, transaction_ts DESC)
    WHERE customer_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_payment_one_row_per_sale
    ON pos.payment (sale_id);

CREATE TABLE IF NOT EXISTS pos.prescription_context (
    prescription_context_id uuid PRIMARY KEY,
    sale_id uuid NOT NULL UNIQUE REFERENCES pos.sale_header(sale_id) ON DELETE CASCADE,
    patient_id uuid REFERENCES customer.patient_profile(patient_id),
    anonymous_patient_key text,
    prescription_mode text NOT NULL CHECK (prescription_mode IN ('ACUTE', 'CHRONIC_REPEAT')),
    chronic_repeat boolean NOT NULL,
    recorded_at timestamptz NOT NULL,
    provenance_class text NOT NULL CHECK (provenance_class = 'SYNTHETIC_CALIBRATED'),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (patient_id IS NOT NULL AND anonymous_patient_key IS NULL)
        OR (patient_id IS NULL AND anonymous_patient_key IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_prescription_context_patient
    ON pos.prescription_context (patient_id)
    WHERE patient_id IS NOT NULL;

ALTER TABLE pos.demand_attempt
    ADD COLUMN IF NOT EXISTS simulation_run_token text;
CREATE INDEX IF NOT EXISTS idx_demand_attempt_run_outcome
    ON pos.demand_attempt (simulation_run_token, outcome);

CREATE UNLOGGED TABLE IF NOT EXISTS staging.stage7e_branch_scope (
    branch_id uuid PRIMARY KEY,
    branch_code text NOT NULL,
    governorate_code text NOT NULL,
    locality_type text NOT NULL,
    timezone text NOT NULL,
    is_24_hours boolean NOT NULL,
    checkout_points integer NOT NULL,
    service_modes text NOT NULL,
    pharmacy_type text NOT NULL,
    demand_index numeric(12,6) NOT NULL,
    customer_discount_ceiling_pct numeric(10,6) NOT NULL,
    cash_share numeric(10,6) NOT NULL,
    card_share numeric(10,6) NOT NULL,
    digital_wallet_share numeric(10,6) NOT NULL,
    third_party_payer_share numeric(10,6) NOT NULL
);

CREATE UNLOGGED TABLE IF NOT EXISTS staging.stage7e_customer_pool (
    branch_id uuid NOT NULL,
    branch_customer_seq integer NOT NULL,
    customer_id uuid NOT NULL,
    household_id uuid NOT NULL,
    loyalty_account_id uuid,
    customer_segment text NOT NULL,
    chronic_repeat_purchase_pattern boolean NOT NULL,
    prescription_purchase_ratio numeric(10,6) NOT NULL,
    preferred_payment_method text NOT NULL,
    average_basket_size numeric(8,4) NOT NULL,
    discount_sensitivity numeric(10,6) NOT NULL,
    delivery_preference numeric(10,6) NOT NULL,
    PRIMARY KEY (branch_id, branch_customer_seq)
);

CREATE UNLOGGED TABLE IF NOT EXISTS staging.stage7e_stock_plan (
    branch_id uuid NOT NULL,
    product_id uuid NOT NULL,
    batch_id uuid NOT NULL UNIQUE,
    sold_units integer NOT NULL,
    closing_buffer_units integer NOT NULL,
    retail_unit_price_egp numeric(14,2) NOT NULL,
    purchase_cost_egp numeric(14,2) NOT NULL,
    last_sale_at timestamptz NOT NULL,
    PRIMARY KEY (branch_id, product_id)
);

CREATE UNLOGGED TABLE IF NOT EXISTS staging.stage7e_stockout_seed (
    demand_attempt_id uuid PRIMARY KEY,
    sale_id uuid NOT NULL,
    branch_id uuid NOT NULL,
    transaction_ts timestamptz NOT NULL,
    product_id uuid NOT NULL,
    requested_units integer NOT NULL,
    correlation_id uuid NOT NULL
);

CREATE UNLOGGED TABLE IF NOT EXISTS staging.stage7e_return_seed (
    return_id uuid PRIMARY KEY,
    sale_id uuid NOT NULL,
    branch_id uuid NOT NULL,
    terminal_id uuid NOT NULL,
    transaction_ts timestamptz NOT NULL,
    correlation_id uuid NOT NULL,
    sale_line_id uuid NOT NULL,
    product_id uuid NOT NULL,
    quantity integer NOT NULL,
    net_sales_egp numeric(16,2) NOT NULL
);

ALTER TABLE staging.stage7e_sale_seed
    ADD COLUMN IF NOT EXISTS customer_id uuid;
ALTER TABLE staging.stage7e_sale_seed
    ADD COLUMN IF NOT EXISTS loyalty_account_id uuid;
ALTER TABLE staging.stage7e_sale_seed
    ADD COLUMN IF NOT EXISTS customer_mode text;
ALTER TABLE staging.stage7e_sale_seed
    ADD COLUMN IF NOT EXISTS anonymous_customer_key text;
ALTER TABLE staging.stage7e_sale_seed
    ADD COLUMN IF NOT EXISTS patient_id uuid;
ALTER TABLE staging.stage7e_sale_seed
    ADD COLUMN IF NOT EXISTS anonymous_patient_key text;
ALTER TABLE staging.stage7e_sale_seed
    ADD COLUMN IF NOT EXISTS customer_segment text;
ALTER TABLE staging.stage7e_sale_seed
    ADD COLUMN IF NOT EXISTS chronic_repeat_purchase_pattern boolean NOT NULL DEFAULT false;
ALTER TABLE staging.stage7e_sale_seed
    ADD COLUMN IF NOT EXISTS prescription_flag boolean NOT NULL DEFAULT false;
ALTER TABLE staging.stage7e_sale_seed
    ADD COLUMN IF NOT EXISTS preferred_payment_method text;
ALTER TABLE staging.stage7e_sale_seed
    ADD COLUMN IF NOT EXISTS average_basket_size numeric(8,4);
ALTER TABLE staging.stage7e_sale_seed
    ADD COLUMN IF NOT EXISTS discount_sensitivity numeric(10,6);
ALTER TABLE staging.stage7e_sale_seed
    ADD COLUMN IF NOT EXISTS delivery_preference numeric(10,6);

ALTER TABLE staging.stage7e_sale_line_seed
    ADD COLUMN IF NOT EXISTS partial_demand boolean NOT NULL DEFAULT false;

GRANT USAGE ON SCHEMA customer TO pharmstock_app, pharmstock_cdc;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA customer TO pharmstock_app;
GRANT SELECT ON ALL TABLES IN SCHEMA customer TO pharmstock_cdc;
GRANT SELECT ON pos.prescription_context TO pharmstock_cdc;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_sale_header_customer_context'
    ) THEN
        ALTER TABLE pos.sale_header
            ADD CONSTRAINT ck_sale_header_customer_context CHECK (
                customer_mode IS NULL
                OR (
                    customer_mode IN ('ANONYMOUS', 'KNOWN', 'LOYALTY', 'DELIVERY_REGISTERED')
                    AND (
                        (customer_mode = 'ANONYMOUS'
                         AND customer_id IS NULL
                         AND loyalty_account_id IS NULL
                         AND anonymous_customer_key IS NOT NULL)
                        OR
                        (customer_mode <> 'ANONYMOUS'
                         AND customer_id IS NOT NULL
                         AND anonymous_customer_key IS NULL)
                    )
                )
            );
    END IF;
END
$$;
