# Stage 6B local run

Set the cloud project and Power BI serving dataset in the current PowerShell:

```powershell
$env:PHARMSTOCK_BQ_PROJECT="pharmstock-ai-platform-2026"
$env:PHARMSTOCK_PBI_DATASET="pharmstock_pbi"
```

Then run:

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 6b
```

Expected final marker:

```text
STAGE_6B_BUILD_KIT_STATUS=PASS
```

This command performs no Power BI Desktop mutation and no Google Cloud mutation.
