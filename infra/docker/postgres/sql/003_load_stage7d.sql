\set ON_ERROR_STOP on

TRUNCATE TABLE
    staging.product,
    staging.product_price_history,
    staging.pharmacy_organization,
    staging.pharmacy_branch,
    staging.product_unit_economics,
    staging.branch_commercial_policy;

\copy staging.product (product_id, market_product_key, trade_name_en, trade_name_ar, scientific_name, manufacturer, drug_class, route, retail_price_egp, currency, market_code, provenance_class, synthetic_record, source_system, source_repository_url, source_license, source_snapshot_label, source_record_number, official_authority, official_registry, official_registration_verified, registration_number, gtin, official_verification_state) FROM '/opt/pharmstock/artifacts/stage7a/egypt_product_master.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');
\copy staging.product_price_history FROM '/opt/pharmstock/artifacts/stage7a/product_price_history.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');
\copy staging.pharmacy_organization FROM '/opt/pharmstock/artifacts/stage7b/production_pharmacy_organizations.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');
\copy staging.pharmacy_branch FROM '/opt/pharmstock/artifacts/stage7b/production_pharmacy_branches.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');
\copy staging.product_unit_economics FROM '/opt/pharmstock/artifacts/stage7c/product_unit_economics.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');
\copy staging.branch_commercial_policy FROM '/opt/pharmstock/artifacts/stage7c/branch_commercial_policy.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');

BEGIN;

INSERT INTO audit.ingestion_run(stage, source_label, status, input_row_counts)
VALUES (
    '7D',
    'stage7a+stage7b+stage7c',
    'RUNNING',
    jsonb_build_object(
        'product', (SELECT count(*) FROM staging.product),
        'price_history', (SELECT count(*) FROM staging.product_price_history),
        'organization', (SELECT count(*) FROM staging.pharmacy_organization),
        'branch', (SELECT count(*) FROM staging.pharmacy_branch),
        'product_economics', (SELECT count(*) FROM staging.product_unit_economics),
        'branch_policy', (SELECT count(*) FROM staging.branch_commercial_policy)
    )
);

INSERT INTO master.product (
    product_id, market_product_key, trade_name_en, trade_name_ar, scientific_name,
    manufacturer, drug_class, route, retail_price_egp, currency, market_code,
    provenance_class, synthetic_record, source_system, source_repository_url,
    source_license, source_snapshot_label, source_record_number, official_authority,
    official_registry, official_registration_verified, registration_number, gtin,
    official_verification_state
)
SELECT
    product_id, market_product_key, trade_name_en, trade_name_ar, scientific_name,
    manufacturer, drug_class, route, retail_price_egp, currency, market_code,
    provenance_class, synthetic_record, source_system, source_repository_url,
    source_license, source_snapshot_label, source_record_number, official_authority,
    official_registry, official_registration_verified,
    nullif(registration_number, ''), nullif(gtin, ''), official_verification_state
FROM staging.product
ON CONFLICT (product_id) DO UPDATE SET
    market_product_key = EXCLUDED.market_product_key,
    trade_name_en = EXCLUDED.trade_name_en,
    trade_name_ar = EXCLUDED.trade_name_ar,
    scientific_name = EXCLUDED.scientific_name,
    manufacturer = EXCLUDED.manufacturer,
    drug_class = EXCLUDED.drug_class,
    route = EXCLUDED.route,
    retail_price_egp = EXCLUDED.retail_price_egp,
    source_snapshot_label = EXCLUDED.source_snapshot_label,
    source_record_number = EXCLUDED.source_record_number,
    official_registration_verified = EXCLUDED.official_registration_verified,
    registration_number = EXCLUDED.registration_number,
    gtin = EXCLUDED.gtin,
    official_verification_state = EXCLUDED.official_verification_state,
    loaded_at = now();

INSERT INTO master.product_price_history (
    price_observation_id, product_id, price_egp, currency, price_type, observed_at,
    source_snapshot_label, source_system, provenance_class, official_price_verified
)
SELECT
    price_observation_id::uuid,
    product_id::uuid,
    price_egp::numeric(14,2),
    currency,
    price_type,
    observed_at::timestamptz,
    source_snapshot_label,
    source_system,
    provenance_class,
    official_price_verified::boolean
FROM staging.product_price_history
ON CONFLICT (price_observation_id) DO UPDATE SET
    price_egp = EXCLUDED.price_egp,
    observed_at = EXCLUDED.observed_at,
    official_price_verified = EXCLUDED.official_price_verified,
    loaded_at = now();

INSERT INTO master.pharmacy_organization (
    organization_id, organization_code, display_name, organization_type,
    planned_branch_count, market_code, provenance_class, synthetic_record
)
SELECT
    organization_id::uuid,
    organization_code,
    display_name,
    organization_type,
    planned_branch_count::integer,
    market_code,
    provenance_class,
    synthetic_record::boolean
FROM staging.pharmacy_organization
ON CONFLICT (organization_id) DO UPDATE SET
    organization_code = EXCLUDED.organization_code,
    display_name = EXCLUDED.display_name,
    organization_type = EXCLUDED.organization_type,
    planned_branch_count = EXCLUDED.planned_branch_count,
    loaded_at = now();

INSERT INTO master.pharmacy_branch (
    branch_id, organization_id, branch_code, display_name, governorate_code,
    governorate, representative_city, locality_type, locality_code, organization_type,
    pharmacy_type, scale, is_24_hours, service_modes, assortment_capacity_skus,
    storage_capacity_units, checkout_points, cold_chain_supported, demand_index,
    governorate_population_2024, governorate_urban_share_2024, branch_expansion_weight,
    market_code, timezone, provenance_class, synthetic_record
)
SELECT
    branch_id::uuid,
    organization_id::uuid,
    branch_code,
    display_name,
    governorate_code,
    governorate,
    representative_city,
    locality_type,
    locality_code,
    organization_type,
    pharmacy_type,
    scale,
    is_24_hours::boolean,
    service_modes,
    assortment_capacity_skus::integer,
    storage_capacity_units::integer,
    checkout_points::integer,
    cold_chain_supported::boolean,
    demand_index::numeric(12,6),
    governorate_population_2024::bigint,
    governorate_urban_share_2024::numeric(10,8),
    branch_expansion_weight::numeric(14,6),
    market_code,
    timezone,
    provenance_class,
    synthetic_record::boolean
FROM staging.pharmacy_branch
ON CONFLICT (branch_id) DO UPDATE SET
    organization_id = EXCLUDED.organization_id,
    branch_code = EXCLUDED.branch_code,
    display_name = EXCLUDED.display_name,
    governorate_code = EXCLUDED.governorate_code,
    governorate = EXCLUDED.governorate,
    representative_city = EXCLUDED.representative_city,
    locality_type = EXCLUDED.locality_type,
    locality_code = EXCLUDED.locality_code,
    organization_type = EXCLUDED.organization_type,
    pharmacy_type = EXCLUDED.pharmacy_type,
    scale = EXCLUDED.scale,
    is_24_hours = EXCLUDED.is_24_hours,
    service_modes = EXCLUDED.service_modes,
    assortment_capacity_skus = EXCLUDED.assortment_capacity_skus,
    storage_capacity_units = EXCLUDED.storage_capacity_units,
    checkout_points = EXCLUDED.checkout_points,
    cold_chain_supported = EXCLUDED.cold_chain_supported,
    demand_index = EXCLUDED.demand_index,
    governorate_population_2024 = EXCLUDED.governorate_population_2024,
    governorate_urban_share_2024 = EXCLUDED.governorate_urban_share_2024,
    branch_expansion_weight = EXCLUDED.branch_expansion_weight,
    loaded_at = now();

INSERT INTO commercial.product_unit_economics (
    product_id, trade_name_en, scientific_name, retail_price_egp,
    retail_price_provenance, official_retail_price_verified, purchase_cost_egp,
    cost_provenance, gross_profit_per_unit_egp, modeled_gross_margin_pct, price_band,
    currency, tax_treatment, tax_component_modeled, financial_model_version
)
SELECT
    product_id::uuid,
    trade_name_en,
    scientific_name,
    retail_price_egp::numeric(14,2),
    retail_price_provenance,
    official_retail_price_verified::boolean,
    purchase_cost_egp::numeric(14,2),
    cost_provenance,
    gross_profit_per_unit_egp::numeric(14,2),
    modeled_gross_margin_pct::numeric(10,6),
    price_band,
    currency,
    tax_treatment,
    tax_component_modeled::boolean,
    financial_model_version
FROM staging.product_unit_economics
ON CONFLICT (product_id) DO UPDATE SET
    trade_name_en = EXCLUDED.trade_name_en,
    scientific_name = EXCLUDED.scientific_name,
    retail_price_egp = EXCLUDED.retail_price_egp,
    purchase_cost_egp = EXCLUDED.purchase_cost_egp,
    gross_profit_per_unit_egp = EXCLUDED.gross_profit_per_unit_egp,
    modeled_gross_margin_pct = EXCLUDED.modeled_gross_margin_pct,
    price_band = EXCLUDED.price_band,
    financial_model_version = EXCLUDED.financial_model_version,
    loaded_at = now();

INSERT INTO commercial.branch_commercial_policy (
    branch_id, governorate_code, governorate, locality_type, organization_type,
    pharmacy_type, scale, customer_discount_ceiling_pct, shrinkage_reserve_pct,
    cash_share, card_share, digital_wallet_share, third_party_payer_share,
    commercial_policy_provenance, financial_model_version
)
SELECT
    branch_id::uuid,
    governorate_code,
    governorate,
    locality_type,
    organization_type,
    pharmacy_type,
    scale,
    customer_discount_ceiling_pct::numeric(10,6),
    shrinkage_reserve_pct::numeric(10,6),
    cash_share::numeric(10,6),
    card_share::numeric(10,6),
    digital_wallet_share::numeric(10,6),
    third_party_payer_share::numeric(10,6),
    commercial_policy_provenance,
    financial_model_version
FROM staging.branch_commercial_policy
ON CONFLICT (branch_id) DO UPDATE SET
    governorate_code = EXCLUDED.governorate_code,
    governorate = EXCLUDED.governorate,
    locality_type = EXCLUDED.locality_type,
    organization_type = EXCLUDED.organization_type,
    pharmacy_type = EXCLUDED.pharmacy_type,
    scale = EXCLUDED.scale,
    customer_discount_ceiling_pct = EXCLUDED.customer_discount_ceiling_pct,
    shrinkage_reserve_pct = EXCLUDED.shrinkage_reserve_pct,
    cash_share = EXCLUDED.cash_share,
    card_share = EXCLUDED.card_share,
    digital_wallet_share = EXCLUDED.digital_wallet_share,
    third_party_payer_share = EXCLUDED.third_party_payer_share,
    financial_model_version = EXCLUDED.financial_model_version,
    loaded_at = now();

INSERT INTO pos.terminal (
    terminal_id, branch_id, terminal_code, terminal_number, terminal_type, is_active
)
SELECT
    uuid_generate_v5(
        '3bf0f220-f0f4-41a1-9782-50534e8f7e8f'::uuid,
        b.branch_id::text || ':terminal:' || terminal_no::text
    ),
    b.branch_id,
    b.branch_code || '-POS-' || lpad(terminal_no::text, 2, '0'),
    terminal_no,
    'POS',
    true
FROM master.pharmacy_branch AS b
CROSS JOIN LATERAL generate_series(1, b.checkout_points) AS terminal_no
ON CONFLICT (terminal_id) DO UPDATE SET
    terminal_code = EXCLUDED.terminal_code,
    is_active = true;

UPDATE audit.ingestion_run
SET status = 'PASS', completed_at = now(), notes = 'Stage 7D deterministic master seed loaded'
WHERE run_id = (
    SELECT run_id FROM audit.ingestion_run
    WHERE stage = '7D' AND status = 'RUNNING'
    ORDER BY started_at DESC
    LIMIT 1
);

COMMIT;
