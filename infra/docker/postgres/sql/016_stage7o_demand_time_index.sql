\set ON_ERROR_STOP on

-- ============================================================
-- PharmStock AI - Stage 7O
-- Demand timestamp serving index.
--
-- Purpose:
--   Fast latest-event lookup and bounded time-window access
--   for Assistant demand-serving workloads.
--
-- IMPORTANT:
--   CREATE INDEX CONCURRENTLY must run outside a transaction.
-- ============================================================

CREATE INDEX CONCURRENTLY IF NOT EXISTS
    idx_demand_attempt_time_desc
ON pos.demand_attempt (
    transaction_ts DESC
);
