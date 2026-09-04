\set ON_ERROR_STOP on
\pset tuples_only on
\pset format unaligned

SELECT 'run_status=' || status
FROM audit.simulation_run
WHERE run_token = :'run_token';

SELECT 'run_profile=' || profile
FROM audit.simulation_run
WHERE run_token = :'run_token';

SELECT 'run_model_version=' || model_version
FROM audit.simulation_run
WHERE run_token = :'run_token';

SELECT 'baseline_database_size_bytes=' || baseline_database_size_bytes
FROM audit.simulation_run
WHERE run_token = :'run_token';

SELECT metric_name || '=' || coalesce(metric_value_text, metric_value_numeric::text)
FROM audit.stage7e_run_metric
WHERE run_token = :'run_token'
ORDER BY metric_name;

SELECT 'demand_arithmetic_guard=' || count(*)
FROM pg_constraint AS c
JOIN pg_class AS t ON t.oid = c.conrelid
JOIN pg_namespace AS n ON n.oid = t.relnamespace
WHERE n.nspname = 'pos'
  AND t.relname = 'demand_attempt'
  AND c.contype = 'c'
  AND pg_get_constraintdef(c.oid) LIKE '%requested_units%fulfilled_units%lost_units%';

SELECT 'header_financial_guard=' || count(*)
FROM pg_constraint AS c
JOIN pg_class AS t ON t.oid = c.conrelid
JOIN pg_namespace AS n ON n.oid = t.relnamespace
WHERE n.nspname = 'pos'
  AND t.relname = 'sale_header'
  AND c.contype = 'c'
  AND pg_get_constraintdef(c.oid) LIKE '%gross_sales_egp%discount_amount_egp%net_sales_egp%';

SELECT 'line_financial_guard=' || count(*)
FROM pg_constraint AS c
JOIN pg_class AS t ON t.oid = c.conrelid
JOIN pg_namespace AS n ON n.oid = t.relnamespace
WHERE n.nspname = 'pos'
  AND t.relname = 'sale_line'
  AND c.contype = 'c'
  AND pg_get_constraintdef(c.oid) LIKE '%gross_sales_egp%discount_amount_egp%net_sales_egp%';

SELECT 'inventory_nonnegative_guard=' || count(*)
FROM pg_constraint AS c
JOIN pg_class AS t ON t.oid = c.conrelid
JOIN pg_namespace AS n ON n.oid = t.relnamespace
WHERE n.nspname = 'inventory'
  AND t.relname = 'stock_movement'
  AND c.contype = 'c'
  AND pg_get_constraintdef(c.oid) LIKE '%balance_after_units%';

SELECT 'sale_customer_context_guard=' || count(*)
FROM pg_constraint AS c
JOIN pg_class AS t ON t.oid = c.conrelid
JOIN pg_namespace AS n ON n.oid = t.relnamespace
WHERE n.nspname = 'pos'
  AND t.relname = 'sale_header'
  AND c.conname = 'ck_sale_header_customer_context';

SELECT 'payment_unique_guard=' || count(*)
FROM pg_indexes
WHERE schemaname = 'pos'
  AND tablename = 'payment'
  AND indexname = 'ux_payment_one_row_per_sale';

SELECT 'customer_direct_identifier_columns=' || count(*)
FROM information_schema.columns
WHERE table_schema = 'customer'
  AND lower(column_name) IN (
      'full_name',
      'first_name',
      'last_name',
      'phone',
      'phone_number',
      'email',
      'address',
      'national_id',
      'passport_number'
  );

SELECT 'privacy_false_guard=' || count(*)
FROM pg_constraint AS c
JOIN pg_class AS t ON t.oid = c.conrelid
JOIN pg_namespace AS n ON n.oid = t.relnamespace
WHERE n.nspname = 'customer'
  AND t.relname IN ('customer_profile', 'patient_profile')
  AND c.contype = 'c'
  AND pg_get_constraintdef(c.oid) LIKE '%direct_identifiers_generated%false%';

SELECT 'prescription_identity_guard=' || count(*)
FROM pg_constraint AS c
JOIN pg_class AS t ON t.oid = c.conrelid
JOIN pg_namespace AS n ON n.oid = t.relnamespace
WHERE n.nspname = 'pos'
  AND t.relname = 'prescription_context'
  AND c.contype = 'c'
  AND pg_get_constraintdef(c.oid) LIKE '%anonymous_patient_key%patient_id%';
