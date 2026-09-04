# Stage 7H v0.29.2 — lint + report fix

This hotfix supersedes v0.29.1.

Fixes:
- wraps the two >100 character lines reported by Ruff (E501);
- uses the `gold` verification result in the final report instead of leaving it unused (F841);
- adds `gold_models` to the report, which is required by the final Stage 7H verification output;
- retains v0.29.1 resume-safe behavior: matching Stage 7H final tables are reused, and missing tables are staged/promoted/deleted one at a time to reduce peak BigQuery storage.

Extract this ZIP directly into the project root and overwrite existing files.

Then run:

```powershell
.\.venv\Scripts\ruff.exe check scripts\run_stage7h_cloud.py
```

Only after Ruff passes, run the cloud command.
