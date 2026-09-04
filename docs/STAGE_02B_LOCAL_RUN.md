# Stage 2B — Local Run (Windows PowerShell)

Run these commands from the project root while `.venv` is active.

## 1. Refresh the editable install after upgrading the stage

```powershell
pip install -e ".[dev]"
```

## 2. Run all automated tests

```powershell
pytest
```

Expected Stage 2B acceptance: all tests pass.

## 3. Run a small live official-data checkpoint

```powershell
python scripts\run_checkpoint.py 2b
```

This requests 100 source records from openFDA and writes outputs under:

```text
artifacts\stage2b\
```

## 4. Build a larger real catalog

```powershell
python scripts\run_stage2b_catalog.py --records 1000 --output artifacts\stage2b-1000
```

Then try:

```powershell
python scripts\run_stage2b_catalog.py --records 5000 --output artifacts\stage2b-5000
```

The API runner intentionally caps this mode before the openFDA deep-paging boundary. Full-snapshot download will be a separate ingestion mode.

## 5. Files to inspect

```text
openfda_ndc_raw.jsonl
  Exact raw source records received.

drug_catalog.csv
  Excel/Power-BI-friendly canonical package-level catalog.

drug_catalog.json
  Full canonical Product representation.

rejected_records.jsonl
  Source rows that failed canonical validation and why.

ingestion_summary.json
  Counts and dataset metadata for the run.
```

## Optional API key
For reliable repeated/high-volume openFDA usage, keep the key outside source code:

```powershell
$env:OPENFDA_API_KEY="YOUR_KEY"
```

Never commit the real key to Git.

## What PASS means
A successful run ends with:

```text
STAGE_2B_STATUS=PASS
```

The important counts are source records received, canonical package SKUs, rejected rows, duplicates, and API pages.
