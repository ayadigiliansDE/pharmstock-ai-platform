\set ON_ERROR_STOP on

-- ============================================================
-- PharmStock AI - Stage 7O
-- Analytical demand completeness contract.
--
-- Purpose:
--   Separate latest operational activity from the latest
--   representative analytical business day.
--
-- Current completeness rule:
--   A business day is COMPLETE when observed branch coverage
--   reaches at least 95% of the expected branch universe for
--   the same provenance class.
--
-- Production evolution:
--   Expected branch universe should eventually be derived from
--   explicit branch lifecycle / active-status metadata.
-- ============================================================


-- ============================================================
-- 1. Daily completeness
-- ============================================================

CREATE OR REPLACE VIEW assistant_api.v_demand_day_completeness
WITH (
    security_barrier = true,
    security_invoker = false
)
AS
WITH expected AS (
    SELECT
        COALESCE(
            NULLIF(BTRIM(provenance_class), ''),
            'UNKNOWN'
        ) AS provenance_class,
        COUNT(*)::bigint AS expected_branches
    FROM master.pharmacy_branch
    GROUP BY
        COALESCE(
            NULLIF(BTRIM(provenance_class), ''),
            'UNKNOWN'
        )
),
observed AS (
    SELECT
        business_date,
        provenance_class,
        COUNT(DISTINCT branch_id)::bigint AS observed_branches,
        SUM(demand_attempts)::bigint AS demand_attempts,
        SUM(requested_units)::bigint AS requested_units,
        SUM(fulfilled_units)::bigint AS fulfilled_units,
        SUM(lost_units)::bigint AS lost_units,
        SUM(stockout_attempts)::bigint AS stockout_attempts
    FROM assistant_api.branch_daily_demand
    GROUP BY
        business_date,
        provenance_class
)
SELECT
    o.business_date,
    o.provenance_class,

    e.expected_branches,
    o.observed_branches,

    ROUND(
        o.observed_branches::numeric /
        NULLIF(e.expected_branches, 0)::numeric,
        6
    ) AS branch_coverage_ratio,

    0.950000::numeric AS required_branch_coverage_ratio,

    CASE
        WHEN e.expected_branches > 0
         AND (
            o.observed_branches::numeric /
            e.expected_branches::numeric
         ) >= 0.95
        THEN 'COMPLETE'
        ELSE 'INCOMPLETE'
    END AS completeness_status,

    o.demand_attempts,
    o.requested_units,
    o.fulfilled_units,
    o.lost_units,
    o.stockout_attempts

FROM observed AS o
JOIN expected AS e
  ON e.provenance_class = o.provenance_class;


-- ============================================================
-- 2. Latest representative analytical business day
-- ============================================================

CREATE OR REPLACE VIEW assistant_api.v_demand_analytical_as_of
WITH (
    security_barrier = true,
    security_invoker = false
)
AS
SELECT
    provenance_class,
    MAX(business_date) AS analytical_as_of_date
FROM assistant_api.v_demand_day_completeness
WHERE completeness_status = 'COMPLETE'
GROUP BY provenance_class;


-- ============================================================
-- 3. Least-privilege grants
-- ============================================================

REVOKE ALL
ON assistant_api.v_demand_day_completeness
FROM PUBLIC;

REVOKE ALL
ON assistant_api.v_demand_analytical_as_of
FROM PUBLIC;

GRANT SELECT
ON assistant_api.v_demand_day_completeness
TO pharmstock_workbench;

GRANT SELECT
ON assistant_api.v_demand_analytical_as_of
TO pharmstock_workbench;
