# Stage 7K v0.34.1 — Ruff I001 Import Ordering Hotfix

This patch fixes the two Ruff I001 import-order findings reported after v0.34.0.

Changed files:
- `ml/stage7k/train.py`
- `scripts/run_stage7k.py`

No ML logic, quality gates, BigQuery behavior, MLflow behavior, Docker configuration,
cloud behavior, model serialization, training data, or serving behavior changed.

Apply at the repository root, then run:

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest tests\test_stage7k_ml.py -q
.\.venv\Scripts\python.exe scripts\run_stage7k.py --execute --no-build
```
