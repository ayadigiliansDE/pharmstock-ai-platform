# Stage 2E patch — apply over v0.8.1

This ZIP is intentionally flat. Extract its **contents directly into the existing
`pharmstock-ai-platform-v2` project root** and allow Windows to replace matching files.
It does not contain `.venv` or `artifacts`.

Then run:

```powershell
pip install -e ".[dev]"
python -c "import pharmstock; print(pharmstock.__version__)"
pytest
ruff check .
python scripts\run_checkpoint.py 2e
```

Expected version: `0.9.0`.

Applied to the Windows v0.8.1 checkpoint that had 86 passing tests, this patch adds
14 tests, so the expected test total is `100 passed`.

Stage 2D must already have completed successfully and contain:

```text
artifacts\stage2d\_SUCCESS
```

Stage 2E does not generate prices or revenue.
