# Stage 7I v0.30.1 lint hotfix

Root-relative hotfix for Stage 7I v0.30.0.

Changes:
- sorts `urllib` / `uuid` imports in `scripts/run_stage7i_cdc.py`
- removes five unused Stage 7I constant imports
- sorts imports in `tests/test_stage7i_cdc.py`
- no runtime/CDC/storage-policy logic changed

Apply over the project root, then run:

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest tests\test_stage7i_cdc.py -q
```
