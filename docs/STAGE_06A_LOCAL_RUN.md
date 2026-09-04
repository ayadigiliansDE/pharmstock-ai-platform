# Stage 6A — Windows local run

```powershell
$env:PHARMSTOCK_BQ_PROJECT="pharmstock-ai-platform-2026"
$env:PHARMSTOCK_DBT_BASE_DATASET="pharmstock"
$env:PHARMSTOCK_PBI_DATASET="pharmstock_pbi"
$env:PHARMSTOCK_BQ_LOCATION="EU"

.\.venv\Scripts\python.exe scripts\run_checkpoint.py 6a
```

Expected final line:

```text
STAGE_6A_STATUS=PASS
```

Dry-run cloud deployment:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage6a_powerbi.py `
  --project pharmstock-ai-platform-2026 `
  --base-dataset pharmstock `
  --pbi-dataset pharmstock_pbi `
  --location EU
```

Real deployment only after the dry run succeeds:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage6a_powerbi.py `
  --project pharmstock-ai-platform-2026 `
  --base-dataset pharmstock `
  --pbi-dataset pharmstock_pbi `
  --location EU `
  --execute
```
