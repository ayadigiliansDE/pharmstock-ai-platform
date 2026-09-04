PharmStock Stage 7N v0.38.0 — Power BI Production Semantic Layer

Extract this archive into the repository root and choose Replace/Overwrite.

Run:
  .\.venv\Scripts\ruff.exe check .
  .\.venv\Scripts\python.exe -m pytest tests\test_stage7n_powerbi_prod.py -q
  .\.venv\Scripts\python.exe scripts\run_stage7n_powerbi.py

Only after dry-run PASS:
  $env:PHARMSTOCK_BQ_PROJECT="pharmstock-ai-bq2-2026"
  $env:PHARMSTOCK_BQ_SANDBOX="1"
  .\.venv\Scripts\python.exe scripts\run_stage7n_powerbi.py --execute

Stage 7N creates metadata-only BigQuery views plus read-only PostgreSQL BI views.
It creates no BigQuery data-copy tables and grants no BI writeback privilege.
