# Stage 2F.1 — Local Run Guide

Prerequisite: Stage 2E must already exist at `artifacts/stage2e` with `_SUCCESS`.

```powershell
pip install -e ".[dev]"
python -c "import pharmstock; print(pharmstock.__version__)"
pytest
ruff check .
python scripts\run_checkpoint.py 2f1
```

Expected version:

```text
0.10.1
```

Expected test-suite size for this checkpoint:

```text
123 passed
```

The final command should print:

```text
Synthetic suppliers:      153
Preferred panel / branch: 12
...
STAGE_2F1_STATUS=PASS
```

Open these files first:

1. `artifacts\stage2f1\supplier_master.csv`
2. `artifacts\stage2f1\branch_supplier_panels.csv`
3. `artifacts\stage2f1\supplier_utilization.csv`
4. `artifacts\stage2f1\branch_procurement_kpis.csv`
5. `artifacts\stage2f1\procurement_manifest.json`

The old Stage 2F checkpoint is still available:

```powershell
python scripts\run_checkpoint.py 2f
```

It intentionally preserves the original six-supplier learning checkpoint.
