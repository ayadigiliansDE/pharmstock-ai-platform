\set ON_ERROR_STOP on
\pset tuples_only on
\pset format unaligned

SELECT 'postgres_version=' || current_setting('server_version');
SELECT 'wal_level=' || current_setting('wal_level');
SELECT 'max_replication_slots=' || current_setting('max_replication_slots');
SELECT 'max_wal_senders=' || current_setting('max_wal_senders');
SELECT 'password_encryption=' || current_setting('password_encryption');
SELECT 'product=' || count(*) FROM master.product;
SELECT 'price_history=' || count(*) FROM master.product_price_history;
SELECT 'organization=' || count(*) FROM master.pharmacy_organization;
SELECT 'branch=' || count(*) FROM master.pharmacy_branch;
SELECT 'governorates=' || count(DISTINCT governorate_code) FROM master.pharmacy_branch;
SELECT 'product_economics=' || count(*) FROM commercial.product_unit_economics;
SELECT 'branch_policy=' || count(*) FROM commercial.branch_commercial_policy;
SELECT 'terminal=' || count(*) FROM pos.terminal;
SELECT 'sale_header=' || count(*) FROM pos.sale_header;
SELECT 'sale_line=' || count(*) FROM pos.sale_line;
SELECT 'cdc_role=' || count(*) FROM pg_roles
WHERE rolname = 'pharmstock_cdc' AND rolreplication;
SELECT 'app_role=' || count(*) FROM pg_roles
WHERE rolname = 'pharmstock_app';
SELECT 'publication=' || count(*) FROM pg_publication
WHERE pubname = 'pharmstock_cdc_publication';
SELECT 'publication_tables=' || count(*) FROM pg_publication_tables
WHERE pubname = 'pharmstock_cdc_publication';
SELECT 'product_finance_orphans=' || count(*)
FROM commercial.product_unit_economics e
LEFT JOIN master.product p USING (product_id)
WHERE p.product_id IS NULL;
SELECT 'branch_policy_orphans=' || count(*)
FROM commercial.branch_commercial_policy c
LEFT JOIN master.pharmacy_branch b USING (branch_id)
WHERE b.branch_id IS NULL;
SELECT 'branch_org_orphans=' || count(*)
FROM master.pharmacy_branch b
LEFT JOIN master.pharmacy_organization o USING (organization_id)
WHERE o.organization_id IS NULL;
SELECT 'price_product_orphans=' || count(*)
FROM master.product_price_history h
LEFT JOIN master.product p USING (product_id)
WHERE p.product_id IS NULL;
SELECT 'economics_price_mismatch=' || count(*)
FROM commercial.product_unit_economics e
JOIN master.product p USING (product_id)
WHERE e.retail_price_egp <> p.retail_price_egp;
