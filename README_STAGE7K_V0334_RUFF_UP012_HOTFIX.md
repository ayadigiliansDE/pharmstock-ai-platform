# Stage 7K v0.33.4 — Ruff UP012 Hotfix

Applies on top of Stage 7K v0.33.3.

Changes only `src/pharmstock/ml/offline_history.py`:
- replaces two redundant `.encode("utf-8")` calls with `.encode()` to satisfy Ruff UP012.
- no algorithm, data-generation, ML, BigQuery, MLflow, Docker, storage, or cloud behavior changes.

After extraction to the project root, run:

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest tests\test_stage7k_ml.py -q
.\.venv\Scripts\python.exe scripts\run_stage7k.py --execute --no-build
```
