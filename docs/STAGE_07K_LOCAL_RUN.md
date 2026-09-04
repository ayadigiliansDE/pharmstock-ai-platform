# Stage 7K v0.34.2 local run

PowerShell from the repository root:

```powershell
$env:PHARMSTOCK_BQ_PROJECT="pharmstock-ai-bq2-2026"
$env:PHARMSTOCK_BQ_SANDBOX="1"

.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest tests\test_stage7k_ml.py -q
.\.venv\Scripts\python.exe scripts\run_stage7k.py
.\.venv\Scripts\python.exe scripts\run_stage7k.py --execute --no-build
```

`--no-build` is correct when the existing Stage 7K image already contains the
pinned v0.34.2 dependency set (`mlflow==3.15.2`, sklearn/pandas/numpy/pyarrow and
BigQuery client). The source code is bind-mounted into trainer/serving.

Local endpoints after PASS:

- MLflow: `http://localhost:5001`
- Model API: `http://localhost:8090`
- API docs: `http://localhost:8090/docs`

Do not use `--remove-orphans`; other project services are intentionally
preserved. Stage 7K suppresses the harmless Compose orphan warning without
removing any container.
