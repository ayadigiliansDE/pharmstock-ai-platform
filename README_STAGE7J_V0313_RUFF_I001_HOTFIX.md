# PharmStock Stage 7J v0.31.3 Ruff I001 Hotfix

Fixes Ruff I001 in `tests/test_stage7j_observability.py` by sorting standard-library imports.

No runtime, Airflow, BigQuery, PostgreSQL, or DAG behavior changes are included.

Validation performed:
- `python -m py_compile`: PASS
- `python -m pytest tests/test_stage7j_observability.py -q`: 8 passed
- Full selected regression: 138 passed

Apply at repository root and overwrite the existing test file, then run:

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest tests\test_stage7j_observability.py -q
```
