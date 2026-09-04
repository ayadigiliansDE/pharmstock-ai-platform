# Stage 2E — Windows / PowerShell local run

Run from the project root with the Python 3.14 virtual environment activated.

## 1. Install the Stage 2E patch

```powershell
pip install -e ".[dev]"
```

Confirm the package:

```powershell
python -c "import pharmstock; print(pharmstock.__version__)"
```

Expected:

```text
0.9.0
```

## 2. Acceptance tests + lint

```powershell
pytest
ruff check .
```

When this patch is applied to the v0.8.1 checkpoint that passed on Windows, Stage 2E adds 14 tests.
Expected total:

```text
100 passed
All checks passed!
```

## 3. Run the visible 7-day checkpoint

Stage 2D must already contain `_SUCCESS`:

```powershell
python scripts\run_checkpoint.py 2e
```

Expected final marker:

```text
STAGE_2E_STATUS=PASS
```

The command uses the existing `artifacts\stage2d` dataset and writes:

```text
artifacts\stage2e\demand_lines\
artifacts\stage2e\batch_allocations\
artifacts\stage2e\stock_movements\
artifacts\stage2e\reorder_triggers\
artifacts\stage2e\ending_inventory\
artifacts\stage2e\ending_batches\
artifacts\stage2e\daily_branch_kpis.csv
artifacts\stage2e\demand_manifest.json
artifacts\stage2e\_SUCCESS
```

Start by opening `daily_branch_kpis.csv` in Excel. It shows one row per branch/day with baskets,
requested units, fulfilled units, lost units, stockout lines, reorder triggers and fulfillment rate.

## 4. Explicit custom horizon

Example 30-day run:

```powershell
python scripts\run_stage2e_demand.py `
  --stage2d artifacts\stage2d `
  --start-date 2026-08-22 `
  --days 30 `
  --seed 20260822 `
  --output artifacts\stage2e-30d
```

The simulation is deterministic for a fixed Stage 2D dataset + demand seed + date horizon.

## 5. What to compare with Stage 2D

Stage 2D is a static stock snapshot. Stage 2E advances that state through simulated time:

```text
Stage 2D: initial stock + batches
Stage 2E: demand -> FEFO -> fulfilled/lost units -> stock movement -> reorder -> ending stock
```

No prices or revenue should appear in Stage 2E outputs.
