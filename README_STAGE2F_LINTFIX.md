# Stage 2F Ruff lint hotfix

This flat patch changes only two test files:

- `tests/test_procurement_domain.py`
- `tests/test_procurement_simulation.py`

The fix removes one extra blank line after each import block so Ruff I001 passes.
No production code or business logic is changed. Project version remains `0.10.0`.

Apply this archive directly over the project root, then run:

```powershell
pytest
ruff check .
python scripts\run_checkpoint.py 2f
```

Expected functional test result: `114 passed`.
