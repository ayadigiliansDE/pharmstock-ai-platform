# Stage 7K v0.33.6 — MLflow skops trusted-types hotfix

Fixes MLflow 3.15.2 refusing to serialize PharmStock's custom sklearn-compatible wrappers.

The patch keeps MLflow's safer `skops` serialization. It does **not** fall back to pickle or cloudpickle.
Only the four internal Stage 7K wrapper types are explicitly trusted, and the `ml/` package is embedded
as a model code dependency for portable loading.

Changed files:
- `ml/stage7k/train.py`
- `tests/test_stage7k_ml.py`

No BigQuery writes, no cloud deployment, no billing changes, no registry deletion.
