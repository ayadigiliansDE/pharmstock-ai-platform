\set ON_ERROR_STOP on

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS commercial;
CREATE SCHEMA IF NOT EXISTS inventory;
CREATE SCHEMA IF NOT EXISTS master;
CREATE SCHEMA IF NOT EXISTS pos;
CREATE SCHEMA IF NOT EXISTS procurement;
CREATE SCHEMA IF NOT EXISTS staging;

CREATE TABLE IF NOT EXISTS audit.ingestion_run (
    run_id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    stage text NOT NULL,
    source_label text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    status text NOT NULL CHECK (status IN ('RUNNING', 'PASS', 'FAIL')),
    input_row_counts jsonb NOT NULL DEFAULT '{}'::jsonb,
    notes text
);

CREATE TABLE IF NOT EXISTS master.product (
    product_id uuid PRIMARY KEY,
    market_product_key text NOT NULL UNIQUE,
    trade_name_en text NOT NULL,
    trade_name_ar text NOT NULL DEFAULT '',
    scientific_name text NOT NULL,
    manufacturer text NOT NULL DEFAULT '',
    drug_class text NOT NULL DEFAULT '',
    route text NOT NULL DEFAULT '',
    retail_price_egp numeric(14,2) NOT NULL CHECK (retail_price_egp > 0),
    currency char(3) NOT NULL CHECK (currency = 'EGP'),
    market_code char(2) NOT NULL CHECK (market_code = 'EG'),
    provenance_class text NOT NULL CHECK (provenance_class = 'PUBLIC_MARKET_EGYPT'),
    synthetic_record boolean NOT NULL CHECK (synthetic_record = false),
    source_system text NOT NULL,
    source_repository_url text NOT NULL,
    source_license text NOT NULL,
    source_snapshot_label text NOT NULL,
    source_record_number integer NOT NULL CHECK (source_record_number > 0),
    official_authority text NOT NULL,
    official_registry text NOT NULL,
    official_registration_verified boolean NOT NULL DEFAULT false,
    registration_number text,
    gtin text,
    official_verification_state text NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_product_trade_name_en ON master.product (trade_name_en);
CREATE INDEX IF NOT EXISTS idx_product_scientific_name ON master.product (scientific_name);
CREATE INDEX IF NOT EXISTS idx_product_manufacturer ON master.product (manufacturer);

CREATE TABLE IF NOT EXISTS master.product_price_history (
    price_observation_id uuid PRIMARY KEY,
    product_id uuid NOT NULL REFERENCES master.product(product_id),
    price_egp numeric(14,2) NOT NULL CHECK (price_egp > 0),
    currency char(3) NOT NULL CHECK (currency = 'EGP'),
    price_type text NOT NULL,
    observed_at timestamptz NOT NULL,
    source_snapshot_label text NOT NULL,
    source_system text NOT NULL,
    provenance_class text NOT NULL CHECK (provenance_class = 'PUBLIC_MARKET_EGYPT'),
    official_price_verified boolean NOT NULL DEFAULT false,
    loaded_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (product_id, source_snapshot_label, price_egp)
);

CREATE INDEX IF NOT EXISTS idx_price_history_product_observed
    ON master.product_price_history (product_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS master.pharmacy_organization (
    organization_id uuid PRIMARY KEY,
    organization_code text NOT NULL UNIQUE,
    display_name text NOT NULL,
    organization_type text NOT NULL,
    planned_branch_count integer NOT NULL CHECK (planned_branch_count > 0),
    market_code char(2) NOT NULL CHECK (market_code = 'EG'),
    provenance_class text NOT NULL CHECK (provenance_class = 'SYNTHETIC_CALIBRATED'),
    synthetic_record boolean NOT NULL CHECK (synthetic_record = true),
    loaded_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS master.pharmacy_branch (
    branch_id uuid PRIMARY KEY,
    organization_id uuid NOT NULL REFERENCES master.pharmacy_organization(organization_id),
    branch_code text NOT NULL UNIQUE,
    display_name text NOT NULL,
    governorate_code text NOT NULL,
    governorate text NOT NULL,
    representative_city text NOT NULL,
    locality_type text NOT NULL CHECK (locality_type IN ('urban', 'rural')),
    locality_code text NOT NULL,
    organization_type text NOT NULL,
    pharmacy_type text NOT NULL,
    scale text NOT NULL,
    is_24_hours boolean NOT NULL,
    service_modes text NOT NULL,
    assortment_capacity_skus integer NOT NULL CHECK (assortment_capacity_skus > 0),
    storage_capacity_units integer NOT NULL CHECK (storage_capacity_units > 0),
    checkout_points integer NOT NULL CHECK (checkout_points > 0),
    cold_chain_supported boolean NOT NULL,
    demand_index numeric(12,6) NOT NULL CHECK (demand_index > 0),
    governorate_population_2024 bigint NOT NULL CHECK (governorate_population_2024 > 0),
    governorate_urban_share_2024 numeric(10,8) NOT NULL
        CHECK (governorate_urban_share_2024 BETWEEN 0 AND 1),
    branch_expansion_weight numeric(14,6) NOT NULL CHECK (branch_expansion_weight > 0),
    market_code char(2) NOT NULL CHECK (market_code = 'EG'),
    timezone text NOT NULL DEFAULT 'Africa/Cairo',
    provenance_class text NOT NULL CHECK (provenance_class = 'SYNTHETIC_CALIBRATED'),
    synthetic_record boolean NOT NULL CHECK (synthetic_record = true),
    loaded_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_branch_governorate ON master.pharmacy_branch (governorate_code);
CREATE INDEX IF NOT EXISTS idx_branch_organization ON master.pharmacy_branch (organization_id);

CREATE TABLE IF NOT EXISTS commercial.product_unit_economics (
    product_id uuid PRIMARY KEY REFERENCES master.product(product_id),
    trade_name_en text NOT NULL,
    scientific_name text NOT NULL,
    retail_price_egp numeric(14,2) NOT NULL CHECK (retail_price_egp > 0),
    retail_price_provenance text NOT NULL CHECK (retail_price_provenance = 'PUBLIC_MARKET_EGYPT'),
    official_retail_price_verified boolean NOT NULL DEFAULT false,
    purchase_cost_egp numeric(14,2) NOT NULL CHECK (purchase_cost_egp > 0),
    cost_provenance text NOT NULL CHECK (cost_provenance = 'SYNTHETIC_CALIBRATED'),
    gross_profit_per_unit_egp numeric(14,2) NOT NULL,
    modeled_gross_margin_pct numeric(10,6) NOT NULL,
    price_band text NOT NULL,
    currency char(3) NOT NULL CHECK (currency = 'EGP'),
    tax_treatment text NOT NULL,
    tax_component_modeled boolean NOT NULL DEFAULT false,
    financial_model_version text NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now(),
    CHECK (purchase_cost_egp <= retail_price_egp),
    CHECK (modeled_gross_margin_pct BETWEEN 0 AND 1)
);

CREATE TABLE IF NOT EXISTS commercial.branch_commercial_policy (
    branch_id uuid PRIMARY KEY REFERENCES master.pharmacy_branch(branch_id),
    governorate_code text NOT NULL,
    governorate text NOT NULL,
    locality_type text NOT NULL,
    organization_type text NOT NULL,
    pharmacy_type text NOT NULL,
    scale text NOT NULL,
    customer_discount_ceiling_pct numeric(10,6) NOT NULL
        CHECK (customer_discount_ceiling_pct BETWEEN 0 AND 1),
    shrinkage_reserve_pct numeric(10,6) NOT NULL CHECK (shrinkage_reserve_pct BETWEEN 0 AND 1),
    cash_share numeric(10,6) NOT NULL CHECK (cash_share BETWEEN 0 AND 1),
    card_share numeric(10,6) NOT NULL CHECK (card_share BETWEEN 0 AND 1),
    digital_wallet_share numeric(10,6) NOT NULL CHECK (digital_wallet_share BETWEEN 0 AND 1),
    third_party_payer_share numeric(10,6) NOT NULL
        CHECK (third_party_payer_share BETWEEN 0 AND 1),
    commercial_policy_provenance text NOT NULL
        CHECK (commercial_policy_provenance = 'SYNTHETIC_CALIBRATED'),
    financial_model_version text NOT NULL,
    loaded_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        abs(cash_share + card_share + digital_wallet_share + third_party_payer_share - 1)
        <= 0.001
    )
);

CREATE TABLE IF NOT EXISTS pos.terminal (
    terminal_id uuid PRIMARY KEY,
    branch_id uuid NOT NULL REFERENCES master.pharmacy_branch(branch_id),
    terminal_code text NOT NULL UNIQUE,
    terminal_number integer NOT NULL CHECK (terminal_number > 0),
    terminal_type text NOT NULL DEFAULT 'POS',
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (branch_id, terminal_number)
);

CREATE INDEX IF NOT EXISTS idx_terminal_branch ON pos.terminal (branch_id);

CREATE TABLE IF NOT EXISTS inventory.stock_batch (
    batch_id uuid PRIMARY KEY,
    branch_id uuid NOT NULL REFERENCES master.pharmacy_branch(branch_id),
    product_id uuid NOT NULL REFERENCES master.product(product_id),
    batch_code text NOT NULL,
    expiry_date date NOT NULL,
    received_at timestamptz NOT NULL,
    purchase_cost_egp numeric(14,2) NOT NULL CHECK (purchase_cost_egp > 0),
    retail_unit_price_egp numeric(14,2) NOT NULL CHECK (retail_unit_price_egp > 0),
    quantity_received integer NOT NULL CHECK (quantity_received >= 0),
    quantity_on_hand integer NOT NULL CHECK (quantity_on_hand >= 0),
    status text NOT NULL DEFAULT 'ACTIVE',
    provenance_class text NOT NULL DEFAULT 'SYNTHETIC_CALIBRATED',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (branch_id, product_id, batch_code)
);

CREATE INDEX IF NOT EXISTS idx_stock_batch_fefo
    ON inventory.stock_batch (branch_id, product_id, expiry_date, received_at);

CREATE TABLE IF NOT EXISTS inventory.inventory_position (
    branch_id uuid NOT NULL REFERENCES master.pharmacy_branch(branch_id),
    product_id uuid NOT NULL REFERENCES master.product(product_id),
    on_hand_units integer NOT NULL DEFAULT 0 CHECK (on_hand_units >= 0),
    reserved_units integer NOT NULL DEFAULT 0 CHECK (reserved_units >= 0),
    available_units integer GENERATED ALWAYS AS (on_hand_units - reserved_units) STORED,
    reorder_point_units integer NOT NULL DEFAULT 0 CHECK (reorder_point_units >= 0),
    target_stock_units integer NOT NULL DEFAULT 0 CHECK (target_stock_units >= 0),
    last_movement_at timestamptz,
    version bigint NOT NULL DEFAULT 0 CHECK (version >= 0),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (branch_id, product_id),
    CHECK (reserved_units <= on_hand_units)
);

CREATE TABLE IF NOT EXISTS inventory.stock_movement (
    movement_id uuid PRIMARY KEY,
    branch_id uuid NOT NULL REFERENCES master.pharmacy_branch(branch_id),
    product_id uuid NOT NULL REFERENCES master.product(product_id),
    batch_id uuid REFERENCES inventory.stock_batch(batch_id),
    movement_type text NOT NULL,
    quantity_delta integer NOT NULL CHECK (quantity_delta <> 0),
    balance_after_units integer NOT NULL CHECK (balance_after_units >= 0),
    reference_type text,
    reference_id uuid,
    occurred_at timestamptz NOT NULL,
    correlation_id uuid NOT NULL,
    causation_id uuid,
    provenance_class text NOT NULL DEFAULT 'SYNTHETIC_CALIBRATED',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_stock_movement_branch_time
    ON inventory.stock_movement (branch_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_stock_movement_product_time
    ON inventory.stock_movement (product_id, occurred_at DESC);

CREATE TABLE IF NOT EXISTS pos.sale_header (
    sale_id uuid PRIMARY KEY,
    branch_id uuid NOT NULL REFERENCES master.pharmacy_branch(branch_id),
    terminal_id uuid NOT NULL REFERENCES pos.terminal(terminal_id),
    transaction_number text NOT NULL,
    transaction_ts timestamptz NOT NULL,
    channel text NOT NULL,
    currency char(3) NOT NULL CHECK (currency = 'EGP'),
    gross_sales_egp numeric(16,2) NOT NULL CHECK (gross_sales_egp >= 0),
    discount_amount_egp numeric(16,2) NOT NULL CHECK (discount_amount_egp >= 0),
    net_sales_egp numeric(16,2) NOT NULL CHECK (net_sales_egp >= 0),
    cogs_egp numeric(16,2) NOT NULL CHECK (cogs_egp >= 0),
    gross_profit_egp numeric(16,2) NOT NULL,
    gross_margin_pct numeric(10,6) NOT NULL,
    transaction_status text NOT NULL DEFAULT 'COMPLETED',
    provenance_class text NOT NULL DEFAULT 'SYNTHETIC_CALIBRATED',
    correlation_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (branch_id, transaction_number),
    CHECK (round(gross_sales_egp - discount_amount_egp, 2) = net_sales_egp),
    CHECK (round(net_sales_egp - cogs_egp, 2) = gross_profit_egp)
);

CREATE INDEX IF NOT EXISTS idx_sale_header_branch_time ON pos.sale_header (branch_id, transaction_ts);

CREATE TABLE IF NOT EXISTS pos.sale_line (
    sale_line_id uuid PRIMARY KEY,
    sale_id uuid NOT NULL REFERENCES pos.sale_header(sale_id) ON DELETE CASCADE,
    line_number integer NOT NULL CHECK (line_number > 0),
    product_id uuid NOT NULL REFERENCES master.product(product_id),
    batch_id uuid REFERENCES inventory.stock_batch(batch_id),
    quantity integer NOT NULL CHECK (quantity > 0),
    retail_unit_price_egp numeric(14,2) NOT NULL CHECK (retail_unit_price_egp > 0),
    discount_pct numeric(10,6) NOT NULL CHECK (discount_pct BETWEEN 0 AND 1),
    selling_unit_price_egp numeric(14,2) NOT NULL CHECK (selling_unit_price_egp >= 0),
    gross_sales_egp numeric(16,2) NOT NULL CHECK (gross_sales_egp >= 0),
    discount_amount_egp numeric(16,2) NOT NULL CHECK (discount_amount_egp >= 0),
    net_sales_egp numeric(16,2) NOT NULL CHECK (net_sales_egp >= 0),
    purchase_cost_egp numeric(14,2) NOT NULL CHECK (purchase_cost_egp > 0),
    cogs_egp numeric(16,2) NOT NULL CHECK (cogs_egp >= 0),
    gross_profit_egp numeric(16,2) NOT NULL,
    gross_margin_pct numeric(10,6) NOT NULL,
    tax_treatment text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (sale_id, line_number),
    CHECK (round(gross_sales_egp - discount_amount_egp, 2) = net_sales_egp),
    CHECK (round(net_sales_egp - cogs_egp, 2) = gross_profit_egp)
);

CREATE INDEX IF NOT EXISTS idx_sale_line_product ON pos.sale_line (product_id);

CREATE TABLE IF NOT EXISTS pos.payment (
    payment_id uuid PRIMARY KEY,
    sale_id uuid NOT NULL REFERENCES pos.sale_header(sale_id) ON DELETE CASCADE,
    payment_method text NOT NULL,
    amount_egp numeric(16,2) NOT NULL CHECK (amount_egp > 0),
    status text NOT NULL DEFAULT 'CAPTURED',
    paid_at timestamptz NOT NULL,
    external_reference text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pos.return_header (
    return_id uuid PRIMARY KEY,
    original_sale_id uuid NOT NULL REFERENCES pos.sale_header(sale_id),
    branch_id uuid NOT NULL REFERENCES master.pharmacy_branch(branch_id),
    terminal_id uuid NOT NULL REFERENCES pos.terminal(terminal_id),
    return_ts timestamptz NOT NULL,
    reason_code text NOT NULL,
    refund_amount_egp numeric(16,2) NOT NULL CHECK (refund_amount_egp >= 0),
    correlation_id uuid NOT NULL,
    provenance_class text NOT NULL DEFAULT 'SYNTHETIC_CALIBRATED',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pos.return_line (
    return_line_id uuid PRIMARY KEY,
    return_id uuid NOT NULL REFERENCES pos.return_header(return_id) ON DELETE CASCADE,
    original_sale_line_id uuid NOT NULL REFERENCES pos.sale_line(sale_line_id),
    product_id uuid NOT NULL REFERENCES master.product(product_id),
    quantity integer NOT NULL CHECK (quantity > 0),
    refund_amount_egp numeric(16,2) NOT NULL CHECK (refund_amount_egp >= 0),
    restock_disposition text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS procurement.supplier (
    supplier_id uuid PRIMARY KEY,
    supplier_code text NOT NULL UNIQUE,
    supplier_name text NOT NULL,
    supplier_type text NOT NULL,
    service_scope text NOT NULL,
    reliability_score numeric(10,6) NOT NULL CHECK (reliability_score BETWEEN 0 AND 1),
    nominal_lead_time_days integer NOT NULL CHECK (nominal_lead_time_days >= 0),
    provenance_class text NOT NULL DEFAULT 'SYNTHETIC_CALIBRATED',
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS procurement.purchase_order (
    purchase_order_id uuid PRIMARY KEY,
    branch_id uuid NOT NULL REFERENCES master.pharmacy_branch(branch_id),
    supplier_id uuid NOT NULL REFERENCES procurement.supplier(supplier_id),
    order_number text NOT NULL UNIQUE,
    ordered_at timestamptz NOT NULL,
    expected_at timestamptz NOT NULL,
    status text NOT NULL,
    currency char(3) NOT NULL CHECK (currency = 'EGP'),
    ordered_cost_egp numeric(16,2) NOT NULL CHECK (ordered_cost_egp >= 0),
    correlation_id uuid NOT NULL,
    provenance_class text NOT NULL DEFAULT 'SYNTHETIC_CALIBRATED',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS procurement.purchase_order_line (
    purchase_order_line_id uuid PRIMARY KEY,
    purchase_order_id uuid NOT NULL
        REFERENCES procurement.purchase_order(purchase_order_id) ON DELETE CASCADE,
    line_number integer NOT NULL CHECK (line_number > 0),
    product_id uuid NOT NULL REFERENCES master.product(product_id),
    ordered_units integer NOT NULL CHECK (ordered_units > 0),
    unit_cost_egp numeric(14,2) NOT NULL CHECK (unit_cost_egp > 0),
    line_cost_egp numeric(16,2) NOT NULL CHECK (line_cost_egp >= 0),
    UNIQUE (purchase_order_id, line_number)
);

CREATE TABLE IF NOT EXISTS procurement.goods_receipt (
    receipt_id uuid PRIMARY KEY,
    purchase_order_id uuid NOT NULL REFERENCES procurement.purchase_order(purchase_order_id),
    branch_id uuid NOT NULL REFERENCES master.pharmacy_branch(branch_id),
    supplier_id uuid NOT NULL REFERENCES procurement.supplier(supplier_id),
    received_at timestamptz NOT NULL,
    status text NOT NULL,
    received_cost_egp numeric(16,2) NOT NULL CHECK (received_cost_egp >= 0),
    correlation_id uuid NOT NULL,
    provenance_class text NOT NULL DEFAULT 'SYNTHETIC_CALIBRATED',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS procurement.goods_receipt_line (
    receipt_line_id uuid PRIMARY KEY,
    receipt_id uuid NOT NULL REFERENCES procurement.goods_receipt(receipt_id) ON DELETE CASCADE,
    purchase_order_line_id uuid NOT NULL
        REFERENCES procurement.purchase_order_line(purchase_order_line_id),
    product_id uuid NOT NULL REFERENCES master.product(product_id),
    received_units integer NOT NULL CHECK (received_units >= 0),
    rejected_units integer NOT NULL DEFAULT 0 CHECK (rejected_units >= 0),
    batch_id uuid REFERENCES inventory.stock_batch(batch_id)
);

CREATE TABLE IF NOT EXISTS staging.product (LIKE master.product INCLUDING DEFAULTS);
ALTER TABLE staging.product DROP COLUMN IF EXISTS loaded_at;
CREATE TABLE IF NOT EXISTS staging.product_price_history (
    price_observation_id text,
    product_id text,
    price_egp text,
    currency text,
    price_type text,
    observed_at text,
    source_snapshot_label text,
    source_system text,
    provenance_class text,
    official_price_verified text
);
CREATE TABLE IF NOT EXISTS staging.pharmacy_organization (
    organization_id text,
    organization_code text,
    display_name text,
    organization_type text,
    planned_branch_count text,
    market_code text,
    provenance_class text,
    synthetic_record text
);
CREATE TABLE IF NOT EXISTS staging.pharmacy_branch (
    branch_id text,
    organization_id text,
    branch_code text,
    display_name text,
    governorate_code text,
    governorate text,
    representative_city text,
    locality_type text,
    locality_code text,
    organization_type text,
    pharmacy_type text,
    scale text,
    is_24_hours text,
    service_modes text,
    assortment_capacity_skus text,
    storage_capacity_units text,
    checkout_points text,
    cold_chain_supported text,
    demand_index text,
    governorate_population_2024 text,
    governorate_urban_share_2024 text,
    branch_expansion_weight text,
    market_code text,
    timezone text,
    provenance_class text,
    synthetic_record text
);
CREATE TABLE IF NOT EXISTS staging.product_unit_economics (
    product_id text,
    trade_name_en text,
    scientific_name text,
    retail_price_egp text,
    retail_price_provenance text,
    official_retail_price_verified text,
    purchase_cost_egp text,
    cost_provenance text,
    gross_profit_per_unit_egp text,
    modeled_gross_margin_pct text,
    price_band text,
    currency text,
    tax_treatment text,
    tax_component_modeled text,
    financial_model_version text
);
CREATE TABLE IF NOT EXISTS staging.branch_commercial_policy (
    branch_id text,
    governorate_code text,
    governorate text,
    locality_type text,
    organization_type text,
    pharmacy_type text,
    scale text,
    customer_discount_ceiling_pct text,
    shrinkage_reserve_pct text,
    cash_share text,
    card_share text,
    digital_wallet_share text,
    third_party_payer_share text,
    commercial_policy_provenance text,
    financial_model_version text
);
