# Stage 7K.5 v0.35.0 — Live Demand CDC Prerequisite

This patch closes a production correctness gap before streaming ML is enabled.

## Why

`pos.sale_line` only records fulfilled sales. Stockout and partial-demand events are recorded in
`pos.demand_attempt`; without its CDC stream, online stockout/reorder features undercount true demand.

## Changes

- keeps the original 13-table Stage 7D publication contract intact;
- extends Stage 7F+ CDC to 14 topics by adding `pos.demand_attempt`;
- migrates an existing PostgreSQL publication idempotently;
- reconciles the Debezium `table.include.list`;
- marks `pos.demand_attempt` as CDC-managed for Stage 7I current-state overlay;
- upgrades legacy 13-topic Stage 7I resume offsets to 14 topics at the new topic low watermark;
- preserves `snapshot.mode=no_data`, so historical Stage 7E rows are not replayed through Kafka.

## Acceptance order

1. `ruff check .`
2. `pytest tests/test_onprem_postgres_contract.py tests/test_stage7f_cdc.py tests/test_stage7g_rebuild.py tests/test_stage7i_cdc.py -q`
3. Re-run Stage 7F to migrate the live publication and connector.
4. Run Stage 7I dry-run / one cycle to normalize offsets and verify the 14-topic shape.

No BigQuery write is required by the Stage 7F migration itself.
