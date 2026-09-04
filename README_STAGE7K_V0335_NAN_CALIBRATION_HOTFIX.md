# Stage 7K v0.33.5 — NaN Calibration Hotfix

Fixes a runtime failure in the zero-cost offline stockout-history generator when
BigQuery aggregate calibration fields contain NULL/NaN values (for example,
`STDDEV_SAMP` on one-observation groups).

The fix adds a finite-number coercion boundary and regression coverage for NaN
calibration inputs. It does not change BigQuery data, cloud storage, model gates,
MLflow state, or CDC state.
