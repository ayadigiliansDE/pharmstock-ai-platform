# Stage 7H v0.29.1 — Resume + Storage Safety Hotfix

Purpose:
- avoid re-uploading Stage 7H tables that were already promoted successfully;
- reduce peak BigQuery storage by staging/promoting/deleting one table at a time;
- show per-Parquet-file upload progress;
- clean the current staging table even if an upload/promotion is interrupted.

Install by extracting this ZIP directly into the project root:
`D:\Data_Engineer_Work_With_VSCode\Projects\pharmstock-ai-platform-v2`

Then run:

```powershell
.\.venv\Scripts\ruff.exe check scripts\run_stage7h_cloud.py
.\.venv\Scripts\python.exe scripts\run_stage7h_cloud.py --execute --replace
```

Do NOT use `--force-reload` for recovery from the v0.29.0 quota failure.
The default mode is resume-safe and will reuse valid Stage 7H final tables.
