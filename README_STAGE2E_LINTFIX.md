# Stage 2E Lint Hotfix

This flat patch fixes the Ruff import-order warning in:

`src/pharmstock/simulation/__init__.py`

No business logic, tests, demand behavior, or package version changes are included.

Apply by extracting the ZIP directly into the project root and choosing Replace/Overwrite.
Then run:

```powershell
pytest
ruff check .
python scripts\run_checkpoint.py 2e
```

Expected:
- 100 tests passed
- Ruff: All checks passed!
- STAGE_2E_STATUS=PASS
