\set ON_ERROR_STOP on

SELECT format('CREATE ROLE pharmstock_app WITH LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pharmstock_app')
\gexec

SELECT format('ALTER ROLE pharmstock_app WITH LOGIN PASSWORD %L', :'app_password')
\gexec

SELECT format(
    'CREATE ROLE pharmstock_cdc WITH LOGIN REPLICATION PASSWORD %L',
    :'cdc_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pharmstock_cdc')
\gexec

SELECT format('ALTER ROLE pharmstock_cdc WITH LOGIN REPLICATION PASSWORD %L', :'cdc_password')
\gexec

GRANT CONNECT ON DATABASE pharmstock_ops TO pharmstock_app, pharmstock_cdc;
GRANT USAGE ON SCHEMA master, commercial, pos, inventory, procurement TO pharmstock_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA pos, inventory, procurement
    TO pharmstock_app;
GRANT SELECT ON ALL TABLES IN SCHEMA master, commercial TO pharmstock_app;

GRANT USAGE ON SCHEMA pos, inventory, procurement TO pharmstock_cdc;
GRANT SELECT ON ALL TABLES IN SCHEMA pos, inventory, procurement TO pharmstock_cdc;

ALTER DEFAULT PRIVILEGES IN SCHEMA pos, inventory, procurement
    GRANT SELECT ON TABLES TO pharmstock_cdc;
ALTER DEFAULT PRIVILEGES IN SCHEMA pos, inventory, procurement
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO pharmstock_app;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'pharmstock_cdc_publication') THEN
        CREATE PUBLICATION pharmstock_cdc_publication FOR TABLE
            pos.sale_header,
            pos.sale_line,
            pos.payment,
            pos.return_header,
            pos.return_line,
            inventory.stock_batch,
            inventory.inventory_position,
            inventory.stock_movement,
            procurement.supplier,
            procurement.purchase_order,
            procurement.purchase_order_line,
            procurement.goods_receipt,
            procurement.goods_receipt_line;
    END IF;
END
$$;
