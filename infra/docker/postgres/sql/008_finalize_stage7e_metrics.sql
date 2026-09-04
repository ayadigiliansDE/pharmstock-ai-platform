\set ON_ERROR_STOP on

BEGIN;

DELETE FROM audit.stage7e_run_metric WHERE run_token = :'run_token';

WITH sale_metrics AS MATERIALIZED (
    SELECT
        count(*)::numeric AS sale_header,
        count(*) FILTER (WHERE customer_id IS NOT NULL)::numeric AS known_sales,
        count(*) FILTER (WHERE customer_id IS NULL)::numeric AS anonymous_sales,
        count(*) FILTER (WHERE loyalty_account_id IS NOT NULL)::numeric AS loyalty_sales,
        count(*) FILTER (WHERE customer_mode = 'DELIVERY_REGISTERED')::numeric
            AS delivery_registered_sales,
        count(*) FILTER (WHERE prescription_flag)::numeric AS prescription_sales,
        count(*) FILTER (
            WHERE customer_id IS NOT NULL AND chronic_repeat_purchase_pattern
        )::numeric AS chronic_repeat_sales,
        count(DISTINCT channel)::numeric AS channels,
        count(DISTINCT payment_method)::numeric AS payment_methods
    FROM staging.stage7e_sale_seed
),
line_metrics AS MATERIALIZED (
    SELECT
        count(*)::numeric AS sale_line,
        count(*) FILTER (WHERE partial_demand)::numeric AS partial_demand_attempts,
        count(*) FILTER (WHERE batch_id IS NULL)::numeric AS lines_without_batch,
        coalesce(round(sum(gross_sales_egp)::numeric, 2), 0) AS gross_sales_egp,
        coalesce(round(sum(net_sales_egp)::numeric, 2), 0) AS net_sales_egp,
        coalesce(round(sum(cogs_egp)::numeric, 2), 0) AS cogs_egp,
        coalesce(round(sum(gross_profit_egp)::numeric, 2), 0) AS gross_profit_egp
    FROM staging.stage7e_sale_line_seed
),
stockout_metrics AS MATERIALIZED (
    SELECT
        count(*)::numeric AS stockout_demand_attempts,
        coalesce(sum(requested_units), 0)::numeric AS stockout_lost_units
    FROM staging.stage7e_stockout_seed
),
branch_metrics AS MATERIALIZED (
    SELECT
        count(*)::numeric AS branches,
        count(DISTINCT governorate_code)::numeric AS governorates,
        count(*) FILTER (
            WHERE audit.stage7e_receipt_delay_days(
                :seed::text || '|receipt-delay|' || branch_id::text
            ) > 0
        )::numeric AS delayed_goods_receipts
    FROM staging.stage7e_branch_scope
),
customer_metrics AS MATERIALIZED (
    SELECT
        count(*)::numeric AS customers,
        count(*) FILTER (WHERE loyalty_account_id IS NOT NULL)::numeric AS loyalty_accounts,
        count(*) FILTER (WHERE customer_segment = 'CHRONIC_REPEAT')::numeric
            AS chronic_customers
    FROM staging.stage7e_customer_pool
),
household_metrics AS MATERIALIZED (
    SELECT count(*)::numeric AS households
    FROM customer.household AS h
    JOIN staging.stage7e_branch_scope AS b
      ON b.branch_id = h.preferred_branch_id
),
patient_metrics AS MATERIALIZED (
    SELECT count(*)::numeric AS patients
    FROM customer.patient_profile AS p
    JOIN customer.household AS h USING (household_id)
    JOIN staging.stage7e_branch_scope AS b
      ON b.branch_id = h.preferred_branch_id
),
prescription_metrics AS MATERIALIZED (
    SELECT count(*)::numeric AS prescription_contexts
    FROM pos.prescription_context AS p
    JOIN staging.stage7e_sale_seed AS s USING (sale_id)
),
stock_metrics AS MATERIALIZED (
    SELECT count(*)::numeric AS stock_batch
    FROM staging.stage7e_stock_plan
),
return_metrics AS MATERIALIZED (
    SELECT count(*)::numeric AS return_header
    FROM staging.stage7e_return_seed
),
all_metrics AS MATERIALIZED (
    SELECT
        sale.*,
        line.*,
        stockout.*,
        branch.*,
        cust.*,
        household.*,
        patient.*,
        prescription.*,
        stock.*,
        retm.*
    FROM sale_metrics AS sale
    CROSS JOIN line_metrics AS line
    CROSS JOIN stockout_metrics AS stockout
    CROSS JOIN branch_metrics AS branch
    CROSS JOIN customer_metrics AS cust
    CROSS JOIN household_metrics AS household
    CROSS JOIN patient_metrics AS patient
    CROSS JOIN prescription_metrics AS prescription
    CROSS JOIN stock_metrics AS stock
    CROSS JOIN return_metrics AS retm
)
INSERT INTO audit.stage7e_run_metric (run_token, metric_name, metric_value_numeric)
SELECT :'run_token', metric_name, metric_value
FROM all_metrics AS m
CROSS JOIN LATERAL (
    VALUES
        ('sale_header', m.sale_header),
        ('sale_line', m.sale_line),
        ('payment', m.sale_header),
        ('demand_attempt', m.sale_line + m.stockout_demand_attempts),
        ('partial_demand_attempts', m.partial_demand_attempts),
        ('stockout_demand_attempts', m.stockout_demand_attempts),
        ('lost_demand_units', m.partial_demand_attempts + m.stockout_lost_units),
        ('return_header', m.return_header),
        ('return_line', m.return_header),
        ('branches', m.branches),
        ('governorates', m.governorates),
        ('channels', m.channels),
        ('payment_methods', m.payment_methods),
        ('known_sales', m.known_sales),
        ('anonymous_sales', m.anonymous_sales),
        ('loyalty_sales', m.loyalty_sales),
        ('delivery_registered_sales', m.delivery_registered_sales),
        ('prescription_sales', m.prescription_sales),
        ('prescription_contexts', m.prescription_contexts),
        ('chronic_repeat_sales', m.chronic_repeat_sales),
        ('customers', m.customers),
        ('households', m.households),
        ('loyalty_accounts', m.loyalty_accounts),
        ('patients', m.patients),
        ('chronic_customers', m.chronic_customers),
        ('batch_rows', m.stock_batch),
        ('inventory_positions', m.stock_batch),
        ('sale_movements', m.sale_line),
        ('opening_receipt_movements', m.stock_batch),
        ('suppliers', 300::numeric),
        ('purchase_orders', m.branches),
        ('purchase_order_lines', m.stock_batch),
        ('goods_receipts', m.branches),
        ('delayed_goods_receipts', m.delayed_goods_receipts),
        ('goods_receipt_lines', m.stock_batch),
        ('lines_without_batch', m.lines_without_batch),
        ('gross_sales_egp', m.gross_sales_egp),
        ('net_sales_egp', m.net_sales_egp),
        ('cogs_egp', m.cogs_egp),
        ('gross_profit_egp', m.gross_profit_egp),
        ('avg_lines_per_sale', round(m.sale_line / NULLIF(m.sale_header, 0), 6)),
        ('return_rate', round(m.return_header / NULLIF(m.sale_header, 0), 6)),
        ('database_size_after_bytes', pg_database_size(current_database())::numeric)
) AS metric(metric_name, metric_value);

INSERT INTO audit.stage7e_run_metric (
    run_token,
    metric_name,
    metric_value_text
)
VALUES (
    :'run_token',
    'audit_strategy',
    'FAST_STAGING_METRICS_NO_FULL_TABLE_RESCAN'
);

UPDATE audit.simulation_run AS run
SET
    generated_counts = (
        SELECT jsonb_object_agg(metric_name, metric_value_numeric)
        FROM audit.stage7e_run_metric
        WHERE run_token = :'run_token'
          AND metric_value_numeric IS NOT NULL
    ),
    notes = 'History committed; fast staging metrics finalized without full operational table rescans; awaiting Python acceptance'
WHERE run.run_token = :'run_token';

COMMIT;
