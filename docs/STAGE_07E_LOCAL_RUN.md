# Stage 7E — Local Windows / PowerShell Run

Prerequisites:

1. Stage 7D must have ended with `STAGE_7D_STATUS=PASS`.
2. Docker Desktop must be running.
3. The `pharmstock-postgres` container and its persistent volume must still exist.
4. Do not run `docker compose down -v`; `-v` removes the PostgreSQL volume.

## Standard acceptance run

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,gcp,analytics]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 7e
```

The default checkpoint uses:

```text
profile = acceptance
branches = 5,000
days = 14
window = 2026-08-09 .. 2026-08-22
base transactions per branch/day = 24 x branch demand_index
```

This is intentionally a heavy local data run. PostgreSQL writes millions of rows and database size
will grow materially. Runtime depends on CPU, SSD speed, Docker Desktop memory and available disk.

v0.26.1 commits generated history before audit finalization. The final audit uses staging metrics
instead of full operational-table rescans. If the process is interrupted after the history commit,
rerunning the same command resumes finalization without regenerating the millions of rows.

## Fast functional smoke run instead

Use this only for troubleshooting, not as final Stage 7E acceptance:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7e_history.py --profile dev
```

## 365-day production-like profile

Do not run this until the acceptance profile is stable and disk capacity has been checked:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7e_history.py `
  --profile prod_like `
  --allow-large-run
```

## Expected acceptance output

The exact counts are measured from PostgreSQL. The run must satisfy at least:

```text
Sale headers:              >= 1,200,000
Sale lines:                >= 2,000,000
Payments:                  exactly one per sale
Demand attempts:           >= sale lines
Partial demand:             > 0
Out-of-stock demand:        > 0
Lost-demand units:          > 0
Demand arithmetic guard:   database CHECK constraint
Branches represented:      5,000
Governorates represented:  27 / 27
Financial guards:           database CHECK constraints
Sale lines without batch:  0
Negative-inventory guard:  database CHECK constraint
Suppliers:                  >= 300
Purchase orders:            5,000
Goods receipts:             5,000
Delayed goods receipts:     > 0 and < 5,000
Customer profiles:          250,000
Households:                 100,000
Patient profiles:           300,000
Known + anonymous sales:    exactly all sales
Prescription contexts:     exactly prescription sales
Customer direct PII:        NOT GENERATED
Audit strategy:             FAST_STAGING_METRICS_NO_FULL_TABLE_RESCAN
Cloud mutation:             NO

STAGE_7E_STATUS=PASS
```

Outputs:

```text
artifacts\stage7e\history_contract.json
artifacts\stage7e\history_run_profile.json
artifacts\stage7e\history_verification.json
artifacts\stage7e\table_counts.json
artifacts\stage7e\_SUCCESS
```
