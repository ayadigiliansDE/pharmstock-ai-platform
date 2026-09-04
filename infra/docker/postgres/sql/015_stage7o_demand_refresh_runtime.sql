\set ON_ERROR_STOP on

-- ============================================================
-- PharmStock AI - Stage 7O
-- Governed incremental refresh runtime for Assistant demand.
--
-- Security:
--   Airflow receives EXECUTE on one controlled function.
--   No direct POS mutation.
--   No direct serving-table mutation.
--   No procurement or decision permissions.
--
-- Refresh strategy:
--   Recompute a bounded Cairo-business-date window.
--   This remains correct when source events are updated/deleted.
-- ============================================================


-- ============================================================
-- 1. Dedicated Airflow refresh principal
-- ============================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname = 'pharmstock_assistant_refresh'
    ) THEN
        CREATE ROLE pharmstock_assistant_refresh LOGIN;
    END IF;
END
$$;

SELECT format(
    'ALTER ROLE pharmstock_assistant_refresh WITH LOGIN PASSWORD %L',
    :'refresh_password'
)
\gexec

GRANT CONNECT ON DATABASE pharmstock_ops
TO pharmstock_assistant_refresh;

GRANT USAGE ON SCHEMA assistant_api
TO pharmstock_assistant_refresh;


-- ============================================================
-- 2. Controlled refresh function
--
-- Normal Airflow run:
--   SELECT assistant_api.refresh_branch_daily_demand(2);
--
-- Wider reconciliation:
--   SELECT assistant_api.refresh_branch_daily_demand(35);
-- ============================================================

CREATE OR REPLACE FUNCTION assistant_api.refresh_branch_daily_demand(
    p_lookback_days integer DEFAULT 2
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_data_as_of date;
    v_start_date date;
    v_rows_written bigint := 0;
    v_source_events bigint := 0;
BEGIN
    IF p_lookback_days < 1 OR p_lookback_days > 90 THEN
        RAISE EXCEPTION
            'p_lookback_days must be between 1 and 90; received %',
            p_lookback_days;
    END IF;

    -- Prevent overlapping refresh jobs.
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtext(
            'assistant_api.branch_daily_demand_refresh'
        )::bigint
    );

    SELECT
        MAX(
            (d.transaction_ts AT TIME ZONE 'Africa/Cairo')::date
        )
    INTO v_data_as_of
    FROM pos.demand_attempt AS d;

    IF v_data_as_of IS NULL THEN
        RETURN pg_catalog.jsonb_build_object(
            'status', 'NO_SOURCE_DATA',
            'lookback_days', p_lookback_days
        );
    END IF;

    v_start_date :=
        v_data_as_of - (p_lookback_days - 1);

    -- Delete the bounded aggregate window first.
    -- This makes UPDATE/DELETE corrections in the raw source
    -- converge correctly instead of accumulating stale values.
    DELETE FROM assistant_api.branch_daily_demand
    WHERE business_date BETWEEN v_start_date AND v_data_as_of;

    INSERT INTO assistant_api.branch_daily_demand (
        business_date,
        branch_id,
        provenance_class,
        demand_attempts,
        requested_units,
        fulfilled_units,
        lost_units,
        stockout_attempts,
        first_transaction_at,
        last_transaction_at,
        refreshed_at
    )
    SELECT
        (d.transaction_ts AT TIME ZONE 'Africa/Cairo')::date
            AS business_date,

        d.branch_id,

        COALESCE(
            NULLIF(BTRIM(d.provenance_class), ''),
            'UNKNOWN'
        ) AS provenance_class,

        COUNT(*)::bigint,
        COALESCE(SUM(d.requested_units), 0)::bigint,
        COALESCE(SUM(d.fulfilled_units), 0)::bigint,
        COALESCE(SUM(d.lost_units), 0)::bigint,

        COUNT(*) FILTER (
            WHERE d.outcome = 'OUT_OF_STOCK'
        )::bigint,

        MIN(d.transaction_ts),
        MAX(d.transaction_ts),
        clock_timestamp()

    FROM pos.demand_attempt AS d

    WHERE
        (d.transaction_ts AT TIME ZONE 'Africa/Cairo')::date
            BETWEEN v_start_date AND v_data_as_of

    GROUP BY
        (d.transaction_ts AT TIME ZONE 'Africa/Cairo')::date,
        d.branch_id,
        COALESCE(
            NULLIF(BTRIM(d.provenance_class), ''),
            'UNKNOWN'
        );

    GET DIAGNOSTICS v_rows_written = ROW_COUNT;

    SELECT COUNT(*)::bigint
    INTO v_source_events
    FROM pos.demand_attempt AS d
    WHERE
        (d.transaction_ts AT TIME ZONE 'Africa/Cairo')::date
            BETWEEN v_start_date AND v_data_as_of;

    RETURN pg_catalog.jsonb_build_object(
        'status', 'PASS',
        'business_timezone', 'Africa/Cairo',
        'data_as_of', v_data_as_of,
        'window_start', v_start_date,
        'window_end', v_data_as_of,
        'lookback_days', p_lookback_days,
        'source_events', v_source_events,
        'aggregate_rows_written', v_rows_written
    );
END;
$$;


-- ============================================================
-- 3. Lock down execution surface
-- ============================================================

REVOKE ALL
ON FUNCTION assistant_api.refresh_branch_daily_demand(integer)
FROM PUBLIC;

GRANT EXECUTE
ON FUNCTION assistant_api.refresh_branch_daily_demand(integer)
TO pharmstock_assistant_refresh;


-- Read-only post-refresh validation surfaces.
GRANT SELECT
ON assistant_api.v_branch_daily_demand
TO pharmstock_assistant_refresh;

GRANT SELECT
ON assistant_api.v_demand_day_completeness
TO pharmstock_assistant_refresh;

GRANT SELECT
ON assistant_api.v_demand_analytical_as_of
TO pharmstock_assistant_refresh;


-- ============================================================
-- 4. Explicit least-privilege assertions
-- ============================================================

REVOKE INSERT, UPDATE, DELETE, TRUNCATE
ON assistant_api.branch_daily_demand
FROM pharmstock_assistant_refresh;

REVOKE INSERT, UPDATE, DELETE, TRUNCATE
ON pos.demand_attempt
FROM pharmstock_assistant_refresh;

REVOKE INSERT, UPDATE, DELETE
ON procurement.purchase_order
FROM pharmstock_assistant_refresh;

REVOKE INSERT, UPDATE, DELETE
ON procurement.purchase_order_line
FROM pharmstock_assistant_refresh;

REVOKE INSERT, UPDATE, DELETE
ON procurement.goods_receipt
FROM pharmstock_assistant_refresh;

REVOKE INSERT, UPDATE, DELETE
ON procurement.goods_receipt_line
FROM pharmstock_assistant_refresh;
