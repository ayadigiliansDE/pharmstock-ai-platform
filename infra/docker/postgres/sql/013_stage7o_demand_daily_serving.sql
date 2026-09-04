\set ON_ERROR_STOP on

-- ============================================================
-- PharmStock AI - Stage 7O
-- Branch daily observed-demand serving layer.
--
-- Purpose:
--   Fast interactive demand analytics for the AI Assistant
--   without scanning millions of POS demand events per request.
--
-- Grain:
--   Cairo Business Date x Branch x Provenance
--
-- Governance:
--   Raw POS remains source of truth.
--   Stage 7M workbench role gets VIEW access only.
--   No Assistant write privileges.
-- ============================================================


-- ============================================================
-- 1. Compact serving table
-- ============================================================

CREATE TABLE IF NOT EXISTS assistant_api.branch_daily_demand (
    business_date date NOT NULL,
    branch_id uuid NOT NULL,
    provenance_class text NOT NULL,

    demand_attempts bigint NOT NULL,
    requested_units bigint NOT NULL,
    fulfilled_units bigint NOT NULL,
    lost_units bigint NOT NULL,
    stockout_attempts bigint NOT NULL,

    first_transaction_at timestamptz,
    last_transaction_at timestamptz,

    refreshed_at timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (
        business_date,
        branch_id,
        provenance_class
    )
);


-- Efficient branch trend access.
CREATE INDEX IF NOT EXISTS idx_stage7o_branch_daily_demand_branch_date
ON assistant_api.branch_daily_demand (
    branch_id,
    business_date DESC,
    provenance_class
);


-- Efficient network/provenance trend access.
CREATE INDEX IF NOT EXISTS idx_stage7o_branch_daily_demand_provenance_date
ON assistant_api.branch_daily_demand (
    provenance_class,
    business_date DESC
);


-- ============================================================
-- 2. Initial / idempotent bootstrap from observed POS demand
--
-- Business date is explicitly Cairo time. It therefore does not
-- depend on PostgreSQL session/server timezone.
--
-- Re-running this statement refreshes existing daily partitions
-- rather than creating duplicates.
-- ============================================================

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

    COUNT(*)::bigint AS demand_attempts,

    COALESCE(
        SUM(d.requested_units),
        0
    )::bigint AS requested_units,

    COALESCE(
        SUM(d.fulfilled_units),
        0
    )::bigint AS fulfilled_units,

    COALESCE(
        SUM(d.lost_units),
        0
    )::bigint AS lost_units,

    COUNT(*) FILTER (
        WHERE d.outcome = 'OUT_OF_STOCK'
    )::bigint AS stockout_attempts,

    MIN(d.transaction_ts) AS first_transaction_at,
    MAX(d.transaction_ts) AS last_transaction_at,

    now() AS refreshed_at

FROM pos.demand_attempt AS d

GROUP BY
    (d.transaction_ts AT TIME ZONE 'Africa/Cairo')::date,
    d.branch_id,
    COALESCE(
        NULLIF(BTRIM(d.provenance_class), ''),
        'UNKNOWN'
    )

ON CONFLICT (
    business_date,
    branch_id,
    provenance_class
)
DO UPDATE SET
    demand_attempts       = EXCLUDED.demand_attempts,
    requested_units       = EXCLUDED.requested_units,
    fulfilled_units       = EXCLUDED.fulfilled_units,
    lost_units            = EXCLUDED.lost_units,
    stockout_attempts     = EXCLUDED.stockout_attempts,
    first_transaction_at  = EXCLUDED.first_transaction_at,
    last_transaction_at   = EXCLUDED.last_transaction_at,
    refreshed_at          = EXCLUDED.refreshed_at;


-- ============================================================
-- 3. Governed Assistant read view
-- ============================================================

CREATE OR REPLACE VIEW assistant_api.v_branch_daily_demand
WITH (
    security_barrier = true,
    security_invoker = false
)
AS
SELECT
    d.business_date,

    d.branch_id,
    b.branch_code,
    b.display_name AS branch_name,
    b.governorate,
    b.representative_city,

    d.provenance_class,

    d.demand_attempts,
    d.requested_units,
    d.fulfilled_units,
    d.lost_units,
    d.stockout_attempts,

    CASE
        WHEN d.requested_units > 0
        THEN ROUND(
            d.fulfilled_units::numeric /
            d.requested_units::numeric,
            6
        )
        ELSE NULL
    END AS fill_rate,

    d.first_transaction_at,
    d.last_transaction_at,
    d.refreshed_at

FROM assistant_api.branch_daily_demand AS d

JOIN master.pharmacy_branch AS b
  ON b.branch_id = d.branch_id;


-- ============================================================
-- 4. Least-privilege boundary
-- ============================================================

REVOKE ALL
ON assistant_api.branch_daily_demand
FROM PUBLIC;

REVOKE ALL
ON assistant_api.branch_daily_demand
FROM pharmstock_workbench;

REVOKE ALL
ON assistant_api.v_branch_daily_demand
FROM PUBLIC;

GRANT SELECT
ON assistant_api.v_branch_daily_demand
TO pharmstock_workbench;


-- Explicit serving-layer mutation protection.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
ON assistant_api.branch_daily_demand
FROM pharmstock_workbench;
