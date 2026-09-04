# Stage 2F.1 Patch — Supplier Network Scaling

Apply this flat patch directly over the existing Stage 2F / v0.10.0 project root.
It does not contain `.venv` or `artifacts`.

After extraction on Windows PowerShell:

```powershell
pip install -e ".[dev]"
python -c "import pharmstock; print(pharmstock.__version__)"
pytest
ruff check .
python scripts\run_checkpoint.py 2f1
```

Expected version: `0.10.1`
Expected tests: `123 passed`
Expected scaled supplier network: `153`
Expected final marker: `STAGE_2F1_STATUS=PASS`

The original Stage 2F learning checkpoint is intentionally preserved:

```powershell
python scripts\run_checkpoint.py 2f
```

All supplier identities and supplier service metrics in Stage 2F.1 are synthetic.
