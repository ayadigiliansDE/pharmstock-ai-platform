# Stage 7A — Windows local run

From the project root:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,gcp,analytics]"
.\.venv\Scripts\python.exe -c "import pharmstock; print(pharmstock.__version__)"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 7a
```

Expected package version: `0.22.0`.

The first Stage 7A run downloads the public CC0 Egypt-market CSV from GitHub and caches it. Later
runs reuse the cache. To force a refresh:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7a_egypt_master.py --refresh
```

For an offline copy:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7a_egypt_master.py `
  --source-file D:\path\to\egyptian-drugs.csv
```

A successful run ends with `STAGE_7A_STATUS=PASS` and performs no cloud mutation.
