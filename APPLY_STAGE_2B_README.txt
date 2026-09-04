PharmStock V2 - Stage 2B patch
==============================

This patch is designed to be extracted directly into your existing
pharmstock-ai-platform-v2 project root.

It does NOT contain .venv or artifacts, so your virtual environment and
outputs remain in place.

Windows PowerShell after extraction:

1) Confirm the prompt is inside the project and .venv is active.
2) Refresh editable metadata/dependencies:
   pip install -e ".[dev]"
3) Run regression tests:
   pytest
4) Run the new live checkpoint:
   python scripts\run_checkpoint.py 2b
5) Inspect:
   artifacts\stage2b\drug_catalog.csv
   artifacts\stage2b\ingestion_summary.json

For a larger live catalog:
   python scripts\run_stage2b_catalog.py --records 1000 --output artifacts\stage2b-1000
