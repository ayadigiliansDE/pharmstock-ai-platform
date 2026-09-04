# Stage 3C lint hotfix

Version remains 0.13.0.

Change only: remove unused `pytest` import from `tests/test_durable_processing.py`.
No business logic changes.

Validated in build environment: `150 passed`.
Run on Windows:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 3c
```
