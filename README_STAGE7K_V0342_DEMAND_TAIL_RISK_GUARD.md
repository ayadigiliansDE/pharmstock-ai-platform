# Stage 7K v0.34.2 — Demand Tail-Risk Guard

This cumulative Stage 7K patch is based on v0.34.0 plus the v0.34.1 Ruff import-order fix.

The live v0.34.0 scientific run showed that stockout, reorder and expiry passed, while the
30-day demand hybrid improved MAE but degraded RMSE by 2.22%, just outside the strict 2%
non-inferiority bound. The fix does not loosen the quality gate. Instead, when training uses
SYNTHETIC_CALIBRATED_OFFLINE_BACKFILL, the validation-selected ML correction is capped at
15% of the forecast blend. This limits tail-risk transfer from synthetic calibration while
retaining the baseline safety fallback and the untouched holdout gate. With >=90 days of
observed warehouse history the cap is removed (1.0) and validation may select the full range.

No BigQuery writes, no cloud writes, no billing changes, no volume cleanup, no orphan removal.
