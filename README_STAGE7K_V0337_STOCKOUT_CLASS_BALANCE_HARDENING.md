# Stage 7K v0.33.7 — Stockout Rare-Event Calibration Hardening

This hotfix addresses the data-dependent failure:

`RuntimeError: stockout scientific validation has too few positive labels`

Changes:
- keeps the strict minimum of 50 positive labels per temporal split;
- does **not** fabricate labels and does **not** lower the scientific gate;
- calibrates the offline inventory simulator from observed stockout/lost-demand rates;
- caps current-stock coverage so a single current snapshot is not replayed as a full-year lower bound;
- adds heterogeneous normal / lean / supplier-disruption regimes;
- models missed reorder reviews, partial deliveries, stochastic lead-time delays and demand spikes;
- derives `target_stockout_7d` only from future simulated stockout events;
- prints train/validation/test positive counts and prevalence before classifier training;
- adds regression tests for rare-positive preservation and risk-calibration monotonicity.

No BigQuery writes, no cloud mutation, no billing, no Docker dependency changes.
Apply directly to the project root after v0.33.6.
