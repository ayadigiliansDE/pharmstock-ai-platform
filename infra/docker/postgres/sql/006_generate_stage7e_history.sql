\set ON_ERROR_STOP on

BEGIN;

TRUNCATE TABLE staging.stage7e_product_pool;
TRUNCATE TABLE staging.stage7e_branch_scope;
TRUNCATE TABLE staging.stage7e_customer_pool;
TRUNCATE TABLE staging.stage7e_sale_seed;
TRUNCATE TABLE staging.stage7e_sale_line_seed;
TRUNCATE TABLE staging.stage7e_stock_plan;
TRUNCATE TABLE staging.stage7e_stockout_seed;
TRUNCATE TABLE staging.stage7e_return_seed;

DELETE FROM audit.stage7e_run_metric WHERE run_token = :'run_token';

INSERT INTO audit.simulation_run (
    run_token,
    stage,
    profile,
    model_version,
    provenance_class,
    seed,
    start_date,
    end_date,
    branch_limit,
    base_transactions_per_branch_day,
    baseline_database_size_bytes,
    status,
    notes
)
VALUES (
    :'run_token',
    '7E',
    :'profile',
    :'model_version',
    'SYNTHETIC_CALIBRATED',
    :seed,
    :'start_date'::date,
    :'end_date'::date,
    :branch_limit,
    :base_transactions,
    pg_database_size(current_database()),
    'RUNNING',
    'High-fidelity historical POS workload with privacy-safe customer behavior; direct PII not generated'
);

INSERT INTO staging.stage7e_product_pool (
    product_rn,
    product_id,
    retail_price_egp,
    purchase_cost_egp,
    tax_treatment
)
SELECT
    row_number() OVER (ORDER BY md5(e.product_id::text))::integer,
    e.product_id,
    e.retail_price_egp,
    e.purchase_cost_egp,
    e.tax_treatment
FROM commercial.product_unit_economics AS e
ORDER BY md5(e.product_id::text);

INSERT INTO staging.stage7e_branch_scope (
    branch_id,
    branch_code,
    governorate_code,
    locality_type,
    timezone,
    is_24_hours,
    checkout_points,
    service_modes,
    pharmacy_type,
    demand_index,
    customer_discount_ceiling_pct,
    cash_share,
    card_share,
    digital_wallet_share,
    third_party_payer_share
)
SELECT
    ranked.branch_id,
    ranked.branch_code,
    ranked.governorate_code,
    ranked.locality_type,
    ranked.timezone,
    ranked.is_24_hours,
    ranked.checkout_points,
    ranked.service_modes,
    ranked.pharmacy_type,
    ranked.demand_index,
    ranked.customer_discount_ceiling_pct,
    ranked.cash_share,
    ranked.card_share,
    ranked.digital_wallet_share,
    ranked.third_party_payer_share
FROM (
    SELECT
        b.branch_id,
        b.branch_code,
        b.governorate_code,
        b.locality_type,
        b.timezone,
        b.is_24_hours,
        b.checkout_points,
        b.service_modes,
        b.pharmacy_type,
        b.demand_index,
        p.customer_discount_ceiling_pct,
        p.cash_share,
        p.card_share,
        p.digital_wallet_share,
        p.third_party_payer_share,
        row_number() OVER (
            PARTITION BY b.governorate_code
            ORDER BY b.branch_code
        ) AS governorate_rank
    FROM master.pharmacy_branch AS b
    JOIN commercial.branch_commercial_policy AS p USING (branch_id)
) AS ranked
ORDER BY
    CASE WHEN ranked.governorate_rank = 1 THEN 0 ELSE 1 END,
    ranked.branch_code
LIMIT :branch_limit;

INSERT INTO customer.household (
    household_id,
    household_key,
    preferred_branch_id,
    governorate_code,
    locality_type,
    household_size,
    household_segment,
    provenance_class,
    synthetic_record
)
SELECT
    uuid_generate_v5(
        '71124e74-ae6a-4d76-b4df-0d5c0757f91f'::uuid,
        'EG-HOUSEHOLD-V1|' || b.branch_id::text || '|' || h.household_seq::text
    ),
    'HH-EG-' || substr(md5(b.branch_id::text || '|' || h.household_seq::text), 1, 16),
    b.branch_id,
    b.governorate_code,
    b.locality_type,
    1 + LEAST(
        5,
        floor(
            6 * audit.hash_unit(
                :seed::text || '|household-size|' || b.branch_id::text || '|' || h.household_seq
            )
        )::integer
    ),
    CASE
        WHEN audit.hash_unit(:seed::text || '|household-segment|' || b.branch_id::text || '|' || h.household_seq) < 0.18 THEN 'SINGLE'
        WHEN audit.hash_unit(:seed::text || '|household-segment|' || b.branch_id::text || '|' || h.household_seq) < 0.38 THEN 'COUPLE'
        WHEN audit.hash_unit(:seed::text || '|household-segment|' || b.branch_id::text || '|' || h.household_seq) < 0.82 THEN 'FAMILY'
        ELSE 'MULTIGENERATIONAL'
    END,
    'SYNTHETIC_CALIBRATED',
    true
FROM staging.stage7e_branch_scope AS b
CROSS JOIN generate_series(1, 20) AS h(household_seq)
ON CONFLICT (household_id) DO NOTHING;

WITH customer_basis AS MATERIALIZED (
    SELECT
        b.*,
        c.customer_seq,
        1 + ((c.customer_seq - 1) % 20) AS household_seq,
        audit.hash_unit(:seed::text || '|customer-segment|' || b.branch_id::text || '|' || c.customer_seq) AS segment_u,
        audit.hash_unit(:seed::text || '|customer-age|' || b.branch_id::text || '|' || c.customer_seq) AS age_u,
        audit.hash_unit(:seed::text || '|customer-gender|' || b.branch_id::text || '|' || c.customer_seq) AS gender_u,
        audit.hash_unit(:seed::text || '|customer-loyalty|' || b.branch_id::text || '|' || c.customer_seq) AS loyalty_u,
        audit.hash_unit(:seed::text || '|customer-frequency|' || b.branch_id::text || '|' || c.customer_seq) AS frequency_u,
        audit.hash_unit(:seed::text || '|customer-basket|' || b.branch_id::text || '|' || c.customer_seq) AS basket_u,
        audit.hash_unit(:seed::text || '|customer-discount|' || b.branch_id::text || '|' || c.customer_seq) AS discount_u,
        audit.hash_unit(:seed::text || '|customer-brand|' || b.branch_id::text || '|' || c.customer_seq) AS brand_u,
        audit.hash_unit(:seed::text || '|customer-generic|' || b.branch_id::text || '|' || c.customer_seq) AS generic_u,
        audit.hash_unit(:seed::text || '|customer-delivery|' || b.branch_id::text || '|' || c.customer_seq) AS delivery_u,
        audit.hash_unit(:seed::text || '|customer-payment|' || b.branch_id::text || '|' || c.customer_seq) AS payment_u,
        audit.hash_unit(:seed::text || '|customer-prescription|' || b.branch_id::text || '|' || c.customer_seq) AS prescription_u,
        audit.hash_unit(:seed::text || '|customer-join|' || b.branch_id::text || '|' || c.customer_seq) AS join_u
    FROM staging.stage7e_branch_scope AS b
    CROSS JOIN generate_series(1, 50) AS c(customer_seq)
),
classified AS MATERIALIZED (
    SELECT
        x.*,
        CASE
            WHEN x.segment_u < 0.28 THEN 'CHRONIC_REPEAT'
            WHEN x.segment_u < 0.48 THEN 'FAMILY_CAREGIVER'
            WHEN x.segment_u < 0.78 THEN 'OTC_CONVENIENCE'
            WHEN x.segment_u < 0.92 THEN 'PRICE_SENSITIVE'
            ELSE 'DIGITAL_FIRST'
        END AS customer_segment,
        CASE
            WHEN x.loyalty_u < 0.55 THEN 'NONE'
            WHEN x.loyalty_u < 0.80 THEN 'BRONZE'
            WHEN x.loyalty_u < 0.95 THEN 'SILVER'
            ELSE 'GOLD'
        END AS loyalty_tier
    FROM customer_basis AS x
)
INSERT INTO customer.customer_profile (
    customer_id,
    customer_key,
    household_id,
    preferred_branch_id,
    branch_customer_seq,
    customer_segment,
    age_band,
    gender_marker,
    governorate_code,
    locality_type,
    loyalty_tier,
    join_date,
    purchase_frequency_per_30d,
    average_basket_size,
    discount_sensitivity,
    brand_loyalty_score,
    generic_substitution_tendency,
    preferred_payment_method,
    delivery_preference,
    prescription_purchase_ratio,
    otc_purchase_ratio,
    chronic_repeat_purchase_pattern,
    provenance_class,
    synthetic_record,
    direct_identifiers_generated
)
SELECT
    uuid_generate_v5(
        '59ff66c0-eb90-4e22-985d-f62e38f6b070'::uuid,
        'EG-CUSTOMER-V1|' || x.branch_id::text || '|' || x.customer_seq::text
    ),
    'CUS-EG-' || substr(md5(x.branch_id::text || '|' || x.customer_seq::text), 1, 16),
    uuid_generate_v5(
        '71124e74-ae6a-4d76-b4df-0d5c0757f91f'::uuid,
        'EG-HOUSEHOLD-V1|' || x.branch_id::text || '|' || x.household_seq::text
    ),
    x.branch_id,
    x.customer_seq,
    x.customer_segment,
    CASE
        WHEN x.age_u < 0.24 THEN '18_29'
        WHEN x.age_u < 0.55 THEN '30_44'
        WHEN x.age_u < 0.80 THEN '45_59'
        ELSE '60_PLUS'
    END,
    CASE WHEN x.gender_u < 0.48 THEN 'FEMALE' WHEN x.gender_u < 0.96 THEN 'MALE' ELSE 'UNSPECIFIED' END,
    x.governorate_code,
    x.locality_type,
    x.loyalty_tier,
    :'start_date'::date - floor(90 + 1000 * x.join_u)::integer,
    round((CASE x.customer_segment
        WHEN 'CHRONIC_REPEAT' THEN 1.10 + 0.70 * x.frequency_u
        WHEN 'FAMILY_CAREGIVER' THEN 0.70 + 0.80 * x.frequency_u
        WHEN 'OTC_CONVENIENCE' THEN 0.30 + 0.70 * x.frequency_u
        WHEN 'PRICE_SENSITIVE' THEN 0.40 + 0.70 * x.frequency_u
        ELSE 0.60 + 1.00 * x.frequency_u END)::numeric, 4),
    round((1.20 + 2.10 * x.basket_u)::numeric, 4),
    round(x.discount_u::numeric, 6),
    round((0.20 + 0.75 * x.brand_u)::numeric, 6),
    round((0.10 + 0.85 * x.generic_u)::numeric, 6),
    CASE
        WHEN x.payment_u < x.cash_share THEN 'CASH'
        WHEN x.payment_u < x.cash_share + x.card_share THEN 'CARD'
        WHEN x.payment_u < x.cash_share + x.card_share + x.digital_wallet_share THEN 'DIGITAL_WALLET'
        ELSE 'THIRD_PARTY_PAYER'
    END,
    round((CASE WHEN x.customer_segment = 'DIGITAL_FIRST' THEN 0.65 + 0.30 * x.delivery_u ELSE 0.05 + 0.60 * x.delivery_u END)::numeric, 6),
    round((CASE x.customer_segment
        WHEN 'CHRONIC_REPEAT' THEN 0.74 + 0.20 * x.prescription_u
        WHEN 'FAMILY_CAREGIVER' THEN 0.42 + 0.24 * x.prescription_u
        WHEN 'OTC_CONVENIENCE' THEN 0.06 + 0.16 * x.prescription_u
        WHEN 'PRICE_SENSITIVE' THEN 0.22 + 0.24 * x.prescription_u
        ELSE 0.28 + 0.24 * x.prescription_u END)::numeric, 6),
    round((1 - CASE x.customer_segment
        WHEN 'CHRONIC_REPEAT' THEN 0.74 + 0.20 * x.prescription_u
        WHEN 'FAMILY_CAREGIVER' THEN 0.42 + 0.24 * x.prescription_u
        WHEN 'OTC_CONVENIENCE' THEN 0.06 + 0.16 * x.prescription_u
        WHEN 'PRICE_SENSITIVE' THEN 0.22 + 0.24 * x.prescription_u
        ELSE 0.28 + 0.24 * x.prescription_u END)::numeric, 6),
    x.customer_segment = 'CHRONIC_REPEAT',
    'SYNTHETIC_CALIBRATED',
    true,
    false
FROM classified AS x
ON CONFLICT (customer_id) DO UPDATE SET
    customer_segment = EXCLUDED.customer_segment,
    loyalty_tier = EXCLUDED.loyalty_tier,
    purchase_frequency_per_30d = EXCLUDED.purchase_frequency_per_30d,
    average_basket_size = EXCLUDED.average_basket_size,
    discount_sensitivity = EXCLUDED.discount_sensitivity,
    brand_loyalty_score = EXCLUDED.brand_loyalty_score,
    generic_substitution_tendency = EXCLUDED.generic_substitution_tendency,
    preferred_payment_method = EXCLUDED.preferred_payment_method,
    delivery_preference = EXCLUDED.delivery_preference,
    prescription_purchase_ratio = EXCLUDED.prescription_purchase_ratio,
    otc_purchase_ratio = EXCLUDED.otc_purchase_ratio,
    chronic_repeat_purchase_pattern = EXCLUDED.chronic_repeat_purchase_pattern,
    updated_at = now();

INSERT INTO customer.loyalty_account (
    loyalty_account_id,
    customer_id,
    loyalty_id,
    loyalty_tier,
    points_balance,
    joined_at,
    is_active,
    provenance_class
)
SELECT
    uuid_generate_v5(
        'dc209f3d-076a-43ff-bce8-d39bd6a5c044'::uuid,
        'EG-LOYALTY-V1|' || c.customer_id::text
    ),
    c.customer_id,
    'LOY-EG-' || substr(md5(c.customer_id::text), 1, 16),
    c.loyalty_tier,
    floor(5000 * audit.hash_unit(:seed::text || '|loyalty-points|' || c.customer_id::text))::integer,
    c.join_date,
    true,
    'SYNTHETIC_CALIBRATED'
FROM customer.customer_profile AS c
JOIN staging.stage7e_branch_scope AS b ON b.branch_id = c.preferred_branch_id
WHERE c.loyalty_tier <> 'NONE'
ON CONFLICT (loyalty_account_id) DO NOTHING;

INSERT INTO customer.patient_profile (
    patient_id,
    patient_key,
    household_id,
    household_patient_seq,
    age_band,
    sex_marker,
    relationship_group,
    chronic_profile_band,
    provenance_class,
    synthetic_record,
    direct_identifiers_generated
)
SELECT
    uuid_generate_v5(
        '8b29ea1f-c131-47d6-881c-39b50ba3f5d2'::uuid,
        'EG-PATIENT-V1|' || h.household_id::text || '|' || p.patient_seq::text
    ),
    'PAT-EG-' || substr(md5(h.household_id::text || '|' || p.patient_seq::text), 1, 16),
    h.household_id,
    p.patient_seq,
    CASE p.patient_seq WHEN 1 THEN '30_59' WHEN 2 THEN '0_17' ELSE '60_PLUS' END,
    CASE
        WHEN audit.hash_unit(:seed::text || '|patient-sex|' || h.household_id::text || '|' || p.patient_seq) < 0.49 THEN 'FEMALE'
        WHEN audit.hash_unit(:seed::text || '|patient-sex|' || h.household_id::text || '|' || p.patient_seq) < 0.98 THEN 'MALE'
        ELSE 'UNSPECIFIED'
    END,
    CASE p.patient_seq WHEN 1 THEN 'SELF' WHEN 2 THEN 'CHILD' ELSE 'ADULT_HOUSEHOLD_MEMBER' END,
    CASE
        WHEN p.patient_seq = 2 THEN 'NONE'
        WHEN audit.hash_unit(:seed::text || '|patient-chronic|' || h.household_id::text || '|' || p.patient_seq) < 0.45 THEN 'NONE'
        WHEN audit.hash_unit(:seed::text || '|patient-chronic|' || h.household_id::text || '|' || p.patient_seq) < 0.72 THEN 'LOW'
        WHEN audit.hash_unit(:seed::text || '|patient-chronic|' || h.household_id::text || '|' || p.patient_seq) < 0.92 THEN 'MODERATE'
        ELSE 'HIGH'
    END,
    'SYNTHETIC_CALIBRATED',
    true,
    false
FROM customer.household AS h
JOIN staging.stage7e_branch_scope AS b ON b.branch_id = h.preferred_branch_id
CROSS JOIN generate_series(1, 3) AS p(patient_seq)
ON CONFLICT (patient_id) DO NOTHING;

INSERT INTO staging.stage7e_customer_pool (
    branch_id,
    branch_customer_seq,
    customer_id,
    household_id,
    loyalty_account_id,
    customer_segment,
    chronic_repeat_purchase_pattern,
    prescription_purchase_ratio,
    preferred_payment_method,
    average_basket_size,
    discount_sensitivity,
    delivery_preference
)
SELECT
    c.preferred_branch_id,
    c.branch_customer_seq,
    c.customer_id,
    c.household_id,
    loyalty.loyalty_account_id,
    c.customer_segment,
    c.chronic_repeat_purchase_pattern,
    c.prescription_purchase_ratio,
    c.preferred_payment_method,
    c.average_basket_size,
    c.discount_sensitivity,
    c.delivery_preference
FROM customer.customer_profile AS c
JOIN staging.stage7e_branch_scope AS b ON b.branch_id = c.preferred_branch_id
LEFT JOIN customer.loyalty_account AS loyalty USING (customer_id);

WITH calendar AS MATERIALIZED (
    SELECT (:'start_date'::date + day_offset)::date AS business_date
    FROM generate_series(0, :days - 1) AS gs(day_offset)
),
daily_plan AS MATERIALIZED (
    SELECT
        b.*,
        c.business_date,
        GREATEST(
            1,
            round(
                :base_transactions
                * b.demand_index
                * CASE extract(isodow FROM c.business_date)
                    WHEN 5 THEN 0.88
                    WHEN 6 THEN 0.96
                    ELSE 1.04
                  END
                * (
                    0.88
                    + 0.24 * audit.hash_unit(
                        :seed::text || '|day-volume|' || b.branch_id::text || '|'
                        || c.business_date::text
                    )
                  )
            )::integer
        ) AS transaction_count
    FROM staging.stage7e_branch_scope AS b
    CROSS JOIN calendar AS c
),
transaction_plan AS MATERIALIZED (
    SELECT
        d.*,
        transaction_seq,
        audit.hash_unit(:seed::text || '|txn-time|' || d.branch_id::text || '|' || d.business_date::text || '|' || transaction_seq) AS time_u,
        audit.hash_unit(:seed::text || '|channel|' || d.branch_id::text || '|' || d.business_date::text || '|' || transaction_seq) AS channel_u,
        audit.hash_unit(:seed::text || '|payment|' || d.branch_id::text || '|' || d.business_date::text || '|' || transaction_seq) AS payment_u,
        audit.hash_unit(:seed::text || '|lines|' || d.branch_id::text || '|' || d.business_date::text || '|' || transaction_seq) AS lines_u,
        audit.hash_unit(:seed::text || '|terminal|' || d.branch_id::text || '|' || d.business_date::text || '|' || transaction_seq) AS terminal_u,
        audit.hash_unit(:seed::text || '|known-customer|' || d.branch_id::text || '|' || d.business_date::text || '|' || transaction_seq) AS known_u,
        audit.hash_unit(:seed::text || '|customer-pick|' || d.branch_id::text || '|' || d.business_date::text || '|' || transaction_seq) AS customer_pick_u,
        audit.hash_unit(:seed::text || '|prescription|' || d.branch_id::text || '|' || d.business_date::text || '|' || transaction_seq) AS prescription_u,
        audit.hash_unit(:seed::text || '|patient-pick|' || d.branch_id::text || '|' || d.business_date::text || '|' || transaction_seq) AS patient_u,
        audit.hash_unit(:seed::text || '|payment-adherence|' || d.branch_id::text || '|' || d.business_date::text || '|' || transaction_seq) AS payment_adherence_u
    FROM daily_plan AS d
    CROSS JOIN LATERAL generate_series(1, d.transaction_count) AS gs(transaction_seq)
),
resolved AS MATERIALIZED (
    SELECT
        t.*,
        CASE WHEN t.is_24_hours THEN 0 ELSE 8 * 60 * 60 END AS open_second,
        CASE WHEN t.is_24_hours THEN 24 * 60 * 60 - 1 ELSE 23 * 60 * 60 - 1 END AS close_second,
        CASE
            WHEN t.pharmacy_type = 'fulfillment_center' THEN
                CASE WHEN t.channel_u < 0.56 THEN 'ONLINE_FULFILLMENT' ELSE 'DELIVERY' END
            WHEN position('delivery' IN t.service_modes) > 0 AND t.channel_u < 0.18 THEN 'DELIVERY'
            WHEN position('click_and_collect' IN t.service_modes) > 0 AND t.channel_u < 0.25 THEN 'CLICK_AND_COLLECT'
            ELSE 'IN_STORE'
        END AS channel,
        CASE
            WHEN t.payment_u < t.cash_share THEN 'CASH'
            WHEN t.payment_u < t.cash_share + t.card_share THEN 'CARD'
            WHEN t.payment_u < t.cash_share + t.card_share + t.digital_wallet_share THEN 'DIGITAL_WALLET'
            ELSE 'THIRD_PARTY_PAYER'
        END AS payment_method,
        CASE WHEN t.lines_u < 0.48 THEN 1 WHEN t.lines_u < 0.78 THEN 2 WHEN t.lines_u < 0.94 THEN 3 ELSE 4 END AS line_count
    FROM transaction_plan AS t
),
customer_resolved AS MATERIALIZED (
    SELECT
        r.*,
        cp.customer_id,
        cp.household_id,
        cp.loyalty_account_id,
        cp.customer_segment,
        cp.chronic_repeat_purchase_pattern,
        cp.prescription_purchase_ratio,
        cp.preferred_payment_method,
        cp.average_basket_size,
        cp.discount_sensitivity,
        cp.delivery_preference,
        CASE
            WHEN r.channel IN ('DELIVERY', 'ONLINE_FULFILLMENT') THEN r.known_u < 0.92
            WHEN r.channel = 'CLICK_AND_COLLECT' THEN r.known_u < 0.82
            ELSE r.known_u < 0.60
        END AS is_known
    FROM resolved AS r
    JOIN staging.stage7e_customer_pool AS cp
      ON cp.branch_id = r.branch_id
     AND cp.branch_customer_seq = 1 + LEAST(49, floor(50 * r.customer_pick_u)::integer)
)
INSERT INTO staging.stage7e_sale_seed (
    sale_id,
    branch_id,
    branch_code,
    terminal_id,
    transaction_number,
    transaction_ts,
    channel,
    correlation_id,
    payment_method,
    line_count,
    customer_id,
    loyalty_account_id,
    customer_mode,
    anonymous_customer_key,
    patient_id,
    anonymous_patient_key,
    customer_segment,
    chronic_repeat_purchase_pattern,
    prescription_flag,
    preferred_payment_method,
    average_basket_size,
    discount_sensitivity,
    delivery_preference
)
SELECT
    uuid_generate_v5(
        'aab938f6-3ef0-46ef-82f7-519819a59f4e'::uuid,
        :'run_token' || '|sale|' || r.branch_id::text || '|' || r.business_date::text || '|' || r.transaction_seq::text
    ),
    r.branch_id,
    r.branch_code,
    terminal.terminal_id,
    'S7E-' || :'run_token' || '-' || r.branch_code || '-' || to_char(r.business_date, 'YYYYMMDD') || '-' || lpad(r.transaction_seq::text, 5, '0'),
    (r.business_date::timestamp + make_interval(secs => r.open_second + floor(r.time_u * (r.close_second - r.open_second))::integer)) AT TIME ZONE r.timezone,
    r.channel,
    uuid_generate_v5(
        '9723883f-01b8-494e-a59c-2d8f27b56f7c'::uuid,
        :'run_token' || '|correlation|' || r.branch_id::text || '|' || r.business_date::text || '|' || r.transaction_seq::text
    ),
    CASE
        WHEN r.is_known AND r.payment_adherence_u < 0.72 THEN r.preferred_payment_method
        ELSE r.payment_method
    END,
    CASE
        WHEN r.is_known THEN LEAST(
            4,
            GREATEST(
                1,
                round(r.average_basket_size + (r.lines_u - 0.5) * 1.2)::integer
            )
        )
        ELSE r.line_count
    END,
    CASE WHEN r.is_known THEN r.customer_id END,
    CASE WHEN r.is_known THEN r.loyalty_account_id END,
    CASE
        WHEN NOT r.is_known THEN 'ANONYMOUS'
        WHEN r.channel IN ('DELIVERY', 'ONLINE_FULFILLMENT') THEN 'DELIVERY_REGISTERED'
        WHEN r.loyalty_account_id IS NOT NULL THEN 'LOYALTY'
        ELSE 'KNOWN'
    END,
    CASE WHEN NOT r.is_known THEN 'ANON-EG-' || substr(md5(:'run_token' || '|' || r.branch_id::text || '|' || r.business_date::text || '|' || r.transaction_seq::text), 1, 20) END,
    CASE WHEN r.is_known AND r.prescription_u < r.prescription_purchase_ratio THEN patient.patient_id END,
    CASE WHEN NOT r.is_known AND r.prescription_u < 0.18 THEN 'PAT-ANON-EG-' || substr(md5(:'run_token' || '|patient|' || r.branch_id::text || '|' || r.business_date::text || '|' || r.transaction_seq::text), 1, 20) END,
    CASE WHEN r.is_known THEN r.customer_segment ELSE 'ANONYMOUS' END,
    r.is_known AND r.chronic_repeat_purchase_pattern,
    CASE WHEN r.is_known THEN r.prescription_u < r.prescription_purchase_ratio ELSE r.prescription_u < 0.18 END,
    CASE WHEN r.is_known THEN r.preferred_payment_method ELSE r.payment_method END,
    CASE WHEN r.is_known THEN r.average_basket_size ELSE 1.80 END,
    CASE WHEN r.is_known THEN r.discount_sensitivity ELSE 0.50 END,
    CASE WHEN r.is_known THEN r.delivery_preference ELSE 0.10 END
FROM customer_resolved AS r
JOIN LATERAL (
    SELECT t.terminal_id
    FROM pos.terminal AS t
    WHERE t.branch_id = r.branch_id AND t.is_active
    ORDER BY t.terminal_number
    OFFSET LEAST(r.checkout_points - 1, floor(r.terminal_u * r.checkout_points)::integer)
    LIMIT 1
) AS terminal ON true
LEFT JOIN customer.patient_profile AS patient
  ON patient.household_id = r.household_id
 AND patient.household_patient_seq = 1 + LEAST(2, floor(3 * r.patient_u)::integer);

WITH product_count AS MATERIALIZED (
    SELECT count(*)::integer AS n
    FROM staging.stage7e_product_pool
),
line_plan AS MATERIALIZED (
    SELECT
        s.sale_id,
        s.branch_id,
        s.transaction_ts,
        s.discount_sensitivity,
        line_number,
        CASE
            WHEN s.customer_id IS NOT NULL
             AND s.chronic_repeat_purchase_pattern
             AND line_number = 1
                THEN audit.hash_unit(
                    :seed::text || '|chronic-product|' || s.customer_id::text
                )
            ELSE audit.hash_unit(
                :seed::text || '|product|' || s.sale_id::text || '|' || line_number::text
            )
        END AS product_u,
        audit.hash_unit(
            :seed::text || '|quantity|' || s.sale_id::text || '|' || line_number::text
        ) AS quantity_u,
        audit.hash_unit(
            :seed::text || '|discount-trigger|' || s.sale_id::text || '|' || line_number::text
        ) AS discount_trigger_u,
        audit.hash_unit(
            :seed::text || '|discount-depth|' || s.sale_id::text || '|' || line_number::text
        ) AS discount_depth_u
    FROM staging.stage7e_sale_seed AS s
    CROSS JOIN LATERAL generate_series(1, s.line_count) AS gs(line_number)
),
resolved_line AS MATERIALIZED (
    SELECT
        l.*,
        1 + LEAST(
            p.n - 1,
            floor(power(l.product_u, 2.35) * p.n)::integer
        ) AS product_rn,
        CASE
            WHEN l.quantity_u < 0.84 THEN 1
            WHEN l.quantity_u < 0.96 THEN 2
            WHEN l.quantity_u < 0.99 THEN 3
            ELSE 4
        END AS quantity
    FROM line_plan AS l
    CROSS JOIN product_count AS p
),
financial_basis AS MATERIALIZED (
    SELECT
        l.sale_id,
        l.branch_id,
        l.transaction_ts,
        l.line_number,
        product.product_id,
        l.quantity,
        product.retail_price_egp,
        product.purchase_cost_egp,
        product.tax_treatment,
        CASE
            WHEN l.discount_trigger_u < (0.78 - 0.35 * l.discount_sensitivity) THEN 0::numeric
            ELSE round(
                (
                    policy.customer_discount_ceiling_pct
                    * (0.20 + 0.80 * l.discount_depth_u)
                )::numeric,
                4
            )
        END AS discount_pct
    FROM resolved_line AS l
    JOIN staging.stage7e_product_pool AS product
      ON product.product_rn = l.product_rn
    JOIN commercial.branch_commercial_policy AS policy
      ON policy.branch_id = l.branch_id
),
financial_values AS MATERIALIZED (
    SELECT
        f.*,
        round((f.retail_price_egp * f.quantity)::numeric, 2) AS gross_sales_egp,
        round(
            (f.retail_price_egp * f.quantity * f.discount_pct)::numeric,
            2
        ) AS discount_amount_egp,
        round((f.purchase_cost_egp * f.quantity)::numeric, 2) AS cogs_egp
    FROM financial_basis AS f
),
reconciled AS MATERIALIZED (
    SELECT
        f.*,
        round((f.gross_sales_egp - f.discount_amount_egp)::numeric, 2) AS net_sales_egp
    FROM financial_values AS f
)
INSERT INTO staging.stage7e_sale_line_seed (
    sale_line_id,
    sale_id,
    branch_id,
    transaction_ts,
    line_number,
    product_id,
    quantity,
    retail_unit_price_egp,
    discount_pct,
    selling_unit_price_egp,
    gross_sales_egp,
    discount_amount_egp,
    net_sales_egp,
    purchase_cost_egp,
    cogs_egp,
    gross_profit_egp,
    gross_margin_pct,
    tax_treatment,
    partial_demand
)
SELECT
    uuid_generate_v5(
        '3a29e3cc-f40c-4562-9a78-d4f0629bf546'::uuid,
        :'run_token' || '|sale-line|' || r.sale_id::text || '|' || r.line_number::text
    ),
    r.sale_id,
    r.branch_id,
    r.transaction_ts,
    r.line_number,
    r.product_id,
    r.quantity,
    r.retail_price_egp,
    r.discount_pct,
    round((r.net_sales_egp / r.quantity)::numeric, 2),
    r.gross_sales_egp,
    r.discount_amount_egp,
    r.net_sales_egp,
    r.purchase_cost_egp,
    r.cogs_egp,
    round((r.net_sales_egp - r.cogs_egp)::numeric, 2),
    round(
        ((r.net_sales_egp - r.cogs_egp) / NULLIF(r.net_sales_egp, 0))::numeric,
        6
    ),
    r.tax_treatment,
    audit.hash_unit(:seed::text || '|partial-demand|' || uuid_generate_v5(
        '3a29e3cc-f40c-4562-9a78-d4f0629bf546'::uuid,
        :'run_token' || '|sale-line|' || r.sale_id::text || '|' || r.line_number::text
    )::text) < 0.012
FROM reconciled AS r;

INSERT INTO procurement.supplier (
    supplier_id,
    supplier_code,
    supplier_name,
    supplier_type,
    service_scope,
    reliability_score,
    nominal_lead_time_days,
    provenance_class,
    is_active
)
SELECT
    uuid_generate_v5(
        'f63f395b-763d-4878-a9d5-ab4cb0f85770'::uuid,
        'stage7e-supplier|' || supplier_number::text
    ),
    'S7E-SUP-' || lpad(supplier_number::text, 4, '0'),
    'Synthetic Calibrated Supplier ' || lpad(supplier_number::text, 4, '0'),
    CASE
        WHEN supplier_number <= 30 THEN 'NATIONAL_DISTRIBUTOR'
        WHEN supplier_number <= 120 THEN 'REGIONAL_DISTRIBUTOR'
        WHEN supplier_number <= 260 THEN 'LOCAL_DISTRIBUTOR'
        ELSE 'DIRECT_MANUFACTURER'
    END,
    CASE WHEN supplier_number <= 30 THEN 'NATIONAL' ELSE 'REGIONAL_OR_LOCAL' END,
    round(
        (0.82 + 0.17 * audit.hash_unit(:seed::text || '|supplier-reliability|' || supplier_number))::numeric,
        6
    ),
    1 + floor(6 * audit.hash_unit(:seed::text || '|supplier-lead|' || supplier_number))::integer,
    'SYNTHETIC_CALIBRATED',
    true
FROM generate_series(1, 300) AS gs(supplier_number)
ON CONFLICT (supplier_id) DO NOTHING;

INSERT INTO staging.stage7e_stock_plan (
    branch_id,
    product_id,
    batch_id,
    sold_units,
    closing_buffer_units,
    retail_unit_price_egp,
    purchase_cost_egp,
    last_sale_at
)
SELECT
    line.branch_id,
    line.product_id,
    uuid_generate_v5(
        '07c84c18-bae7-4324-97de-c22687fb409f'::uuid,
        :'run_token' || '|batch|' || line.branch_id::text || '|' || line.product_id::text
    ),
    sum(line.quantity)::integer,
    GREATEST(
        12,
        ceil((sum(line.quantity)::numeric / :days) * 21)::integer
    ),
    max(line.retail_unit_price_egp),
    max(line.purchase_cost_egp),
    max(line.transaction_ts)
FROM staging.stage7e_sale_line_seed AS line
GROUP BY line.branch_id, line.product_id;

INSERT INTO inventory.stock_batch (
    batch_id,
    branch_id,
    product_id,
    batch_code,
    expiry_date,
    received_at,
    purchase_cost_egp,
    retail_unit_price_egp,
    quantity_received,
    quantity_on_hand,
    status,
    provenance_class
)
SELECT
    s.batch_id,
    s.branch_id,
    s.product_id,
    'S7E-' || :'run_token' || '-' || substr(md5(s.branch_id::text || s.product_id::text), 1, 12),
    :'end_date'::date
        + (180 + floor(540 * audit.hash_unit(
            :seed::text || '|expiry|' || s.branch_id::text || '|' || s.product_id::text
          )))::integer,
    (
        :'start_date'::date - 45
        + audit.stage7e_receipt_delay_days(
            :seed::text || '|receipt-delay|' || s.branch_id::text
        )
    )::timestamp AT TIME ZONE 'Africa/Cairo',
    s.purchase_cost_egp,
    s.retail_unit_price_egp,
    s.sold_units + s.closing_buffer_units,
    s.closing_buffer_units,
    'ACTIVE',
    'SYNTHETIC_CALIBRATED'
FROM staging.stage7e_stock_plan AS s
ON CONFLICT (batch_id) DO NOTHING;

UPDATE staging.stage7e_sale_line_seed AS line
SET batch_id = stock.batch_id
FROM staging.stage7e_stock_plan AS stock
WHERE stock.branch_id = line.branch_id
  AND stock.product_id = line.product_id;

INSERT INTO pos.sale_header (
    sale_id,
    branch_id,
    terminal_id,
    transaction_number,
    transaction_ts,
    channel,
    currency,
    gross_sales_egp,
    discount_amount_egp,
    net_sales_egp,
    cogs_egp,
    gross_profit_egp,
    gross_margin_pct,
    transaction_status,
    provenance_class,
    correlation_id,
    simulation_run_token,
    customer_id,
    loyalty_account_id,
    customer_mode,
    anonymous_customer_key,
    prescription_flag
)
SELECT
    seed.sale_id,
    seed.branch_id,
    seed.terminal_id,
    seed.transaction_number,
    seed.transaction_ts,
    seed.channel,
    'EGP',
    round(sum(line.gross_sales_egp)::numeric, 2),
    round(sum(line.discount_amount_egp)::numeric, 2),
    round(sum(line.net_sales_egp)::numeric, 2),
    round(sum(line.cogs_egp)::numeric, 2),
    round(sum(line.gross_profit_egp)::numeric, 2),
    round(
        (sum(line.gross_profit_egp) / NULLIF(sum(line.net_sales_egp), 0))::numeric,
        6
    ),
    'COMPLETED',
    'SYNTHETIC_CALIBRATED',
    seed.correlation_id,
    :'run_token',
    seed.customer_id,
    seed.loyalty_account_id,
    seed.customer_mode,
    seed.anonymous_customer_key,
    seed.prescription_flag
FROM staging.stage7e_sale_seed AS seed
JOIN staging.stage7e_sale_line_seed AS line USING (sale_id)
GROUP BY
    seed.sale_id,
    seed.branch_id,
    seed.terminal_id,
    seed.transaction_number,
    seed.transaction_ts,
    seed.channel,
    seed.correlation_id,
    seed.customer_id,
    seed.loyalty_account_id,
    seed.customer_mode,
    seed.anonymous_customer_key,
    seed.prescription_flag
ON CONFLICT (sale_id) DO NOTHING;

INSERT INTO pos.prescription_context (
    prescription_context_id,
    sale_id,
    patient_id,
    anonymous_patient_key,
    prescription_mode,
    chronic_repeat,
    recorded_at,
    provenance_class
)
SELECT
    uuid_generate_v5(
        'ca7cb927-6600-4b7a-91c2-99ee1d24de98'::uuid,
        :'run_token' || '|prescription|' || seed.sale_id::text
    ),
    seed.sale_id,
    seed.patient_id,
    seed.anonymous_patient_key,
    CASE WHEN seed.chronic_repeat_purchase_pattern THEN 'CHRONIC_REPEAT' ELSE 'ACUTE' END,
    seed.chronic_repeat_purchase_pattern,
    seed.transaction_ts,
    'SYNTHETIC_CALIBRATED'
FROM staging.stage7e_sale_seed AS seed
WHERE seed.prescription_flag
ON CONFLICT (prescription_context_id) DO NOTHING;

INSERT INTO pos.sale_line (
    sale_line_id,
    sale_id,
    line_number,
    product_id,
    batch_id,
    quantity,
    retail_unit_price_egp,
    discount_pct,
    selling_unit_price_egp,
    gross_sales_egp,
    discount_amount_egp,
    net_sales_egp,
    purchase_cost_egp,
    cogs_egp,
    gross_profit_egp,
    gross_margin_pct,
    tax_treatment
)
SELECT
    sale_line_id,
    sale_id,
    line_number,
    product_id,
    batch_id,
    quantity,
    retail_unit_price_egp,
    discount_pct,
    selling_unit_price_egp,
    gross_sales_egp,
    discount_amount_egp,
    net_sales_egp,
    purchase_cost_egp,
    cogs_egp,
    gross_profit_egp,
    gross_margin_pct,
    tax_treatment
FROM staging.stage7e_sale_line_seed
ON CONFLICT (sale_line_id) DO NOTHING;

INSERT INTO pos.payment (
    payment_id,
    sale_id,
    payment_method,
    amount_egp,
    status,
    paid_at,
    external_reference
)
SELECT
    uuid_generate_v5(
        'e755e233-0544-49de-9e13-c36d22653979'::uuid,
        :'run_token' || '|payment|' || sale.sale_id::text
    ),
    sale.sale_id,
    seed.payment_method,
    sale.net_sales_egp,
    'CAPTURED',
    sale.transaction_ts,
    NULL
FROM pos.sale_header AS sale
JOIN staging.stage7e_sale_seed AS seed USING (sale_id)
ON CONFLICT (payment_id) DO NOTHING;

INSERT INTO pos.demand_attempt (
    demand_attempt_id,
    branch_id,
    transaction_ts,
    product_id,
    requested_units,
    fulfilled_units,
    lost_units,
    outcome,
    reason_code,
    linked_sale_id,
    correlation_id,
    provenance_class,
    simulation_run_token
)
SELECT
    uuid_generate_v5(
        'f0fce257-7109-4c4c-a069-e09d37cccfbc'::uuid,
        :'run_token' || '|demand-line|' || line.sale_line_id::text
    ),
    sale.branch_id,
    sale.transaction_ts,
    line.product_id,
    line.quantity + CASE WHEN line.partial_demand THEN 1 ELSE 0 END,
    line.quantity,
    CASE WHEN line.partial_demand THEN 1 ELSE 0 END,
    CASE WHEN line.partial_demand THEN 'PARTIAL' ELSE 'FULFILLED' END,
    CASE WHEN line.partial_demand THEN 'PARTIAL_STOCK' ELSE 'SALE_COMPLETED' END,
    sale.sale_id,
    sale.correlation_id,
    'SYNTHETIC_CALIBRATED',
    :'run_token'
FROM staging.stage7e_sale_line_seed AS line
JOIN staging.stage7e_sale_seed AS sale USING (sale_id)
ON CONFLICT (demand_attempt_id) DO NOTHING;

WITH product_count AS MATERIALIZED (
    SELECT count(*)::integer AS n
    FROM staging.stage7e_product_pool
),
stockout_plan AS MATERIALIZED (
    SELECT
        seed.sale_id,
        seed.branch_id,
        seed.transaction_ts,
        1 + LEAST(
            products.n - 1,
            floor(
                audit.hash_unit(:seed::text || '|stockout-product|' || seed.sale_id::text)
                * products.n
            )::integer
        ) AS product_rn,
        1 + LEAST(
            1,
            floor(
                2 * audit.hash_unit(:seed::text || '|stockout-quantity|' || seed.sale_id::text)
            )::integer
        ) AS requested_units
    FROM staging.stage7e_sale_seed AS seed
    CROSS JOIN product_count AS products
    WHERE audit.hash_unit(:seed::text || '|stockout-trigger|' || seed.sale_id::text) < 0.018
)
INSERT INTO staging.stage7e_stockout_seed (
    demand_attempt_id,
    sale_id,
    branch_id,
    transaction_ts,
    product_id,
    requested_units,
    correlation_id
)
SELECT
    uuid_generate_v5(
        'c1f0048d-352b-4594-9f4d-7ea7e027bb9f'::uuid,
        :'run_token' || '|stockout|' || stockout.sale_id::text
    ),
    stockout.sale_id,
    stockout.branch_id,
    stockout.transaction_ts,
    product.product_id,
    stockout.requested_units,
    uuid_generate_v5(
        '0bc20e1c-2944-4a33-a554-40ac1fb0f12a'::uuid,
        :'run_token' || '|stockout-correlation|' || stockout.sale_id::text
    )
FROM stockout_plan AS stockout
JOIN staging.stage7e_product_pool AS product
  ON product.product_rn = stockout.product_rn
LEFT JOIN staging.stage7e_stock_plan AS stock
  ON stock.branch_id = stockout.branch_id
 AND stock.product_id = product.product_id
WHERE stock.batch_id IS NULL;

INSERT INTO pos.demand_attempt (
    demand_attempt_id,
    branch_id,
    transaction_ts,
    product_id,
    requested_units,
    fulfilled_units,
    lost_units,
    outcome,
    reason_code,
    linked_sale_id,
    correlation_id,
    provenance_class,
    simulation_run_token
)
SELECT
    stockout.demand_attempt_id,
    stockout.branch_id,
    stockout.transaction_ts,
    stockout.product_id,
    stockout.requested_units,
    0,
    stockout.requested_units,
    'OUT_OF_STOCK',
    'NO_SELLABLE_STOCK',
    NULL,
    stockout.correlation_id,
    'SYNTHETIC_CALIBRATED',
    :'run_token'
FROM staging.stage7e_stockout_seed AS stockout
ON CONFLICT (demand_attempt_id) DO NOTHING;

INSERT INTO inventory.inventory_position (
    branch_id,
    product_id,
    on_hand_units,
    reserved_units,
    reorder_point_units,
    target_stock_units,
    last_movement_at,
    version,
    updated_at
)
SELECT
    stock.branch_id,
    stock.product_id,
    stock.closing_buffer_units,
    0,
    GREATEST(5, ceil((stock.sold_units::numeric / :days) * 7)::integer),
    GREATEST(12, ceil((stock.sold_units::numeric / :days) * 21)::integer),
    stock.last_sale_at,
    stock.sold_units,
    now()
FROM staging.stage7e_stock_plan AS stock
ON CONFLICT (branch_id, product_id) DO UPDATE SET
    on_hand_units = EXCLUDED.on_hand_units,
    reserved_units = 0,
    reorder_point_units = EXCLUDED.reorder_point_units,
    target_stock_units = EXCLUDED.target_stock_units,
    last_movement_at = EXCLUDED.last_movement_at,
    version = EXCLUDED.version,
    updated_at = now();

INSERT INTO inventory.stock_movement (
    movement_id,
    branch_id,
    product_id,
    batch_id,
    movement_type,
    quantity_delta,
    balance_after_units,
    reference_type,
    reference_id,
    occurred_at,
    correlation_id,
    causation_id,
    provenance_class
)
SELECT
    uuid_generate_v5(
        'a131482c-9308-4ea7-8412-1643010dcac7'::uuid,
        :'run_token' || '|opening-receipt|' || batch.batch_id::text
    ),
    batch.branch_id,
    batch.product_id,
    batch.batch_id,
    'GOODS_RECEIPT',
    batch.quantity_received,
    batch.quantity_received,
    'OPENING_STOCK',
    batch.batch_id,
    batch.received_at,
    uuid_generate_v5(
        '2b35eaca-3088-4894-bdc8-57288e65a19f'::uuid,
        :'run_token' || '|opening-correlation|' || batch.batch_id::text
    ),
    NULL,
    'SYNTHETIC_CALIBRATED'
FROM inventory.stock_batch AS batch
WHERE batch.batch_code LIKE 'S7E-' || :'run_token' || '-%'
ON CONFLICT (movement_id) DO NOTHING;

WITH sale_movement_plan AS MATERIALIZED (
    SELECT
        line.sale_line_id,
        line.sale_id,
        line.branch_id,
        line.product_id,
        line.batch_id,
        line.quantity,
        line.transaction_ts,
        sale.correlation_id,
        batch.quantity_received
            - sum(line.quantity) OVER (
                PARTITION BY line.batch_id
                ORDER BY line.transaction_ts, line.sale_id, line.line_number
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
              ) AS balance_after_units
    FROM staging.stage7e_sale_line_seed AS line
    JOIN pos.sale_header AS sale USING (sale_id)
    JOIN inventory.stock_batch AS batch USING (batch_id)
)
INSERT INTO inventory.stock_movement (
    movement_id,
    branch_id,
    product_id,
    batch_id,
    movement_type,
    quantity_delta,
    balance_after_units,
    reference_type,
    reference_id,
    occurred_at,
    correlation_id,
    causation_id,
    provenance_class
)
SELECT
    uuid_generate_v5(
        '5bedb07a-2f99-456f-a2c0-b15746493de5'::uuid,
        :'run_token' || '|sale-movement|' || plan.sale_line_id::text
    ),
    plan.branch_id,
    plan.product_id,
    plan.batch_id,
    'SALE',
    -plan.quantity,
    plan.balance_after_units,
    'SALE_LINE',
    plan.sale_line_id,
    plan.transaction_ts,
    plan.correlation_id,
    plan.sale_id,
    'SYNTHETIC_CALIBRATED'
FROM sale_movement_plan AS plan
ON CONFLICT (movement_id) DO NOTHING;

WITH branch_batches AS MATERIALIZED (
    SELECT
        batch.branch_id,
        sum(batch.purchase_cost_egp * batch.quantity_received)::numeric(16,2) AS ordered_cost_egp
    FROM inventory.stock_batch AS batch
    WHERE batch.batch_code LIKE 'S7E-' || :'run_token' || '-%'
    GROUP BY batch.branch_id
),
po_plan AS MATERIALIZED (
    SELECT
        branch.branch_id,
        branch.ordered_cost_egp,
        1 + LEAST(
            299,
            floor(
                300 * audit.hash_unit(
                    :seed::text || '|branch-supplier|' || branch.branch_id::text
                )
            )::integer
        ) AS supplier_number
    FROM branch_batches AS branch
)
INSERT INTO procurement.purchase_order (
    purchase_order_id,
    branch_id,
    supplier_id,
    order_number,
    ordered_at,
    expected_at,
    status,
    currency,
    ordered_cost_egp,
    correlation_id,
    provenance_class
)
SELECT
    uuid_generate_v5(
        '447fa875-7f36-4d3f-82ca-940af1bb37fa'::uuid,
        :'run_token' || '|opening-po|' || plan.branch_id::text
    ),
    plan.branch_id,
    uuid_generate_v5(
        'f63f395b-763d-4878-a9d5-ab4cb0f85770'::uuid,
        'stage7e-supplier|' || plan.supplier_number::text
    ),
    'S7E-' || :'run_token' || '-OPEN-' || substr(md5(plan.branch_id::text), 1, 12),
    (:'start_date'::date - 60)::timestamp AT TIME ZONE 'Africa/Cairo',
    (:'start_date'::date - 45)::timestamp AT TIME ZONE 'Africa/Cairo',
    'RECEIVED',
    'EGP',
    plan.ordered_cost_egp,
    uuid_generate_v5(
        '4b373129-c784-4b5a-95a7-b65763994a11'::uuid,
        :'run_token' || '|opening-po-correlation|' || plan.branch_id::text
    ),
    'SYNTHETIC_CALIBRATED'
FROM po_plan AS plan
ON CONFLICT (purchase_order_id) DO NOTHING;

WITH run_batches AS MATERIALIZED (
    SELECT
        batch.*,
        row_number() OVER (
            PARTITION BY batch.branch_id
            ORDER BY batch.product_id
        )::integer AS line_number
    FROM inventory.stock_batch AS batch
    WHERE batch.batch_code LIKE 'S7E-' || :'run_token' || '-%'
)
INSERT INTO procurement.purchase_order_line (
    purchase_order_line_id,
    purchase_order_id,
    line_number,
    product_id,
    ordered_units,
    unit_cost_egp,
    line_cost_egp
)
SELECT
    uuid_generate_v5(
        'c4f5a867-d5e7-4975-8daf-18f98132b6bc'::uuid,
        :'run_token' || '|opening-po-line|' || batch.branch_id::text || '|'
        || batch.product_id::text
    ),
    uuid_generate_v5(
        '447fa875-7f36-4d3f-82ca-940af1bb37fa'::uuid,
        :'run_token' || '|opening-po|' || batch.branch_id::text
    ),
    batch.line_number,
    batch.product_id,
    batch.quantity_received,
    batch.purchase_cost_egp,
    round((batch.purchase_cost_egp * batch.quantity_received)::numeric, 2)
FROM run_batches AS batch
ON CONFLICT (purchase_order_line_id) DO NOTHING;

WITH po AS MATERIALIZED (
    SELECT
        purchase_order_id,
        branch_id,
        supplier_id,
        ordered_cost_egp,
        correlation_id
    FROM procurement.purchase_order
    WHERE order_number LIKE 'S7E-' || :'run_token' || '-OPEN-%'
)
INSERT INTO procurement.goods_receipt (
    receipt_id,
    purchase_order_id,
    branch_id,
    supplier_id,
    received_at,
    status,
    received_cost_egp,
    correlation_id,
    provenance_class
)
SELECT
    uuid_generate_v5(
        'e1cb0a9e-ec62-455e-9962-4c0cc7c14e09'::uuid,
        :'run_token' || '|opening-receipt|' || po.branch_id::text
    ),
    po.purchase_order_id,
    po.branch_id,
    po.supplier_id,
    (
        :'start_date'::date - 45
        + audit.stage7e_receipt_delay_days(
            :seed::text || '|receipt-delay|' || po.branch_id::text
        )
    )::timestamp AT TIME ZONE 'Africa/Cairo',
    'RECEIVED',
    po.ordered_cost_egp,
    po.correlation_id,
    'SYNTHETIC_CALIBRATED'
FROM po
ON CONFLICT (receipt_id) DO NOTHING;

WITH batch_line AS MATERIALIZED (
    SELECT
        batch.batch_id,
        batch.branch_id,
        batch.product_id,
        batch.quantity_received,
        uuid_generate_v5(
            'c4f5a867-d5e7-4975-8daf-18f98132b6bc'::uuid,
            :'run_token' || '|opening-po-line|' || batch.branch_id::text || '|'
            || batch.product_id::text
        ) AS purchase_order_line_id
    FROM inventory.stock_batch AS batch
    WHERE batch.batch_code LIKE 'S7E-' || :'run_token' || '-%'
)
INSERT INTO procurement.goods_receipt_line (
    receipt_line_id,
    receipt_id,
    purchase_order_line_id,
    product_id,
    received_units,
    rejected_units,
    batch_id
)
SELECT
    uuid_generate_v5(
        '4fe40e55-3c09-4852-83b7-fbc7ef57c764'::uuid,
        :'run_token' || '|opening-receipt-line|' || line.branch_id::text || '|'
        || line.product_id::text
    ),
    uuid_generate_v5(
        'e1cb0a9e-ec62-455e-9962-4c0cc7c14e09'::uuid,
        :'run_token' || '|opening-receipt|' || line.branch_id::text
    ),
    line.purchase_order_line_id,
    line.product_id,
    line.quantity_received,
    0,
    line.batch_id
FROM batch_line AS line
ON CONFLICT (receipt_line_id) DO NOTHING;

INSERT INTO staging.stage7e_return_seed (
    return_id,
    sale_id,
    branch_id,
    terminal_id,
    transaction_ts,
    correlation_id,
    sale_line_id,
    product_id,
    quantity,
    net_sales_egp
)
SELECT
    uuid_generate_v5(
        '37dcc02c-66d6-4170-ae3f-bcb5c60b4833'::uuid,
        :'run_token' || '|return|' || sale.sale_id::text
    ),
    sale.sale_id,
    sale.branch_id,
    sale.terminal_id,
    sale.transaction_ts,
    sale.correlation_id,
    line.sale_line_id,
    line.product_id,
    line.quantity,
    line.net_sales_egp
FROM staging.stage7e_sale_seed AS sale
JOIN staging.stage7e_sale_line_seed AS line
  ON line.sale_id = sale.sale_id
 AND line.line_number = 1
WHERE sale.transaction_ts < (
        (:'end_date'::date - 3)::timestamp AT TIME ZONE 'Africa/Cairo'
      )
  AND audit.hash_unit(:seed::text || '|return|' || sale.sale_id::text) < 0.009;

INSERT INTO pos.return_header (
    return_id,
    original_sale_id,
    branch_id,
    terminal_id,
    return_ts,
    reason_code,
    refund_amount_egp,
    correlation_id,
    provenance_class
)
SELECT
    r.return_id,
    r.sale_id,
    r.branch_id,
    r.terminal_id,
    r.transaction_ts
        + make_interval(
            days => 1 + floor(3 * audit.hash_unit(:seed::text || '|return-delay|' || r.sale_id::text))::integer,
            hours => 1 + floor(8 * audit.hash_unit(:seed::text || '|return-hour|' || r.sale_id::text))::integer
          ),
    CASE
        WHEN audit.hash_unit(:seed::text || '|return-reason|' || r.sale_id::text) < 0.55
            THEN 'CUSTOMER_CHANGED_MIND'
        WHEN audit.hash_unit(:seed::text || '|return-reason|' || r.sale_id::text) < 0.82
            THEN 'WRONG_ITEM'
        ELSE 'PACKAGING_ISSUE'
    END,
    r.net_sales_egp,
    uuid_generate_v5(
        '162ac9fc-e43a-435e-83d4-a3f91591025b'::uuid,
        :'run_token' || '|return-correlation|' || r.sale_id::text
    ),
    'SYNTHETIC_CALIBRATED'
FROM staging.stage7e_return_seed AS r
ON CONFLICT (return_id) DO NOTHING;

INSERT INTO pos.return_line (
    return_line_id,
    return_id,
    original_sale_line_id,
    product_id,
    quantity,
    refund_amount_egp,
    restock_disposition
)
SELECT
    uuid_generate_v5(
        '1d217504-eb7d-4fc2-b22f-2aa3de30da70'::uuid,
        :'run_token' || '|return-line|' || r.return_id::text
    ),
    r.return_id,
    r.sale_line_id,
    r.product_id,
    r.quantity,
    r.net_sales_egp,
    'QUARANTINE'
FROM staging.stage7e_return_seed AS r
ON CONFLICT (return_line_id) DO NOTHING;

UPDATE customer.customer_profile AS customer
SET
    last_purchase_at = activity.last_purchase_at,
    updated_at = now()
FROM (
    SELECT customer_id, max(transaction_ts) AS last_purchase_at
    FROM staging.stage7e_sale_seed
    WHERE customer_id IS NOT NULL
    GROUP BY customer_id
) AS activity
WHERE customer.customer_id = activity.customer_id;

-- Deliberately commit the generated history before audit finalization.  If the
-- verification process is interrupted, the run remains RUNNING and can resume
-- without rolling back/re-generating millions of operational rows.
COMMIT;
