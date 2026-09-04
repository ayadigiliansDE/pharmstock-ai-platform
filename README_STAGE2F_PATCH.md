# Stage 2F flat patch

Extract the **contents** of this ZIP directly into the existing
`pharmstock-ai-platform-v2` project root and allow Windows to replace files.

This patch does not contain `.venv` or generated `artifacts`.

After extraction run:

```powershell
pip install -e ".[dev]"
python -c "import pharmstock; print(pharmstock.__version__)"
pytest
ruff check .
python scripts\run_checkpoint.py 2f
```

Expected version: `0.10.0`
Expected test total: `114 passed`
Expected final marker: `STAGE_2F_STATUS=PASS`
