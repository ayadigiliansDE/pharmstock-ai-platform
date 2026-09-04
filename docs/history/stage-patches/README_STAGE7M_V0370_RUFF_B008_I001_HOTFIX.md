# PharmStock Stage 7M v0.37.0 — Ruff B008/I001 Hotfix

This hotfix is lint-only and does not change Stage 7M API behavior, RBAC, database privileges, workflow transitions, or procurement governance.

## Fixes

- Replaces endpoint default calls such as `Depends(_principal)` with a reusable module-level `PRINCIPAL_DEPENDENCY = Depends(_principal)` singleton. This preserves FastAPI dependency injection while satisfying Ruff `B008`.
- Removes the extra blank line in `tests/test_stage7m_api.py` so the import block satisfies Ruff `I001`.

## Validation performed

- `python -m pytest tests/test_stage7m_api.py -q` -> 18 passed
- Full Stage 7D/7F/7G/7I/7K/7K.5/7L/7M regression -> 130 passed
- Python compile -> PASS
- No modified line exceeds 100 characters

## Apply

Extract this archive into the repository root and overwrite matching files.

Then run:

```powershell
.\.venv\Scripts\ruff.exe check .
```

Expected:

```text
All checks passed!
```

Then run the 130-test regression suite and Stage 7M dry run before `--execute`.
