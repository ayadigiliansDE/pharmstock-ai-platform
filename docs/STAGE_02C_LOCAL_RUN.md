# Stage 2C — Windows Local Run

Assumes Stage 2B has already produced a `drug_catalog.json` file and the `.venv` is active.

## 1. Install the updated editable package

```powershell
pip install -e ".[dev]"
```

## 2. Run the full test suite

```powershell
pytest
```

Expected checkpoint result:

```text
72 passed
```

## 3. Replay Stage 2C with the largest existing Stage 2B catalog

The checkpoint runner first looks for:

```text
artifacts\stage2b-5000\drug_catalog.json
```

and falls back to:

```text
artifacts\stage2b\drug_catalog.json
```

Run:

```powershell
python scripts\run_checkpoint.py 2c
```

The checkpoint generates 25 pharmacy branches so the result is easy to inspect locally.
The final line must be:

```text
STAGE_2C_STATUS=PASS
```

## 4. Inspect the generated files

```text
artifacts\stage2c\branch_inventory.csv
artifacts\stage2c\inventory_batches.csv
artifacts\stage2c\branch_assortment_summary.csv
artifacts\stage2c\inventory_summary.json
```

Open the CSV files in Excel. Confirm that different branches have different SKU counts,
stock quantities, reorder thresholds and batches.

## 5. Explicit command

To use the 5,000-source-record Stage 2B catalog directly:

```powershell
python scripts\run_stage2c_inventory.py `
  --catalog artifacts\stage2b-5000\drug_catalog.json `
  --pharmacies 25 `
  --seed 20260822 `
  --output artifacts\stage2c-25
```

## 6. Scale carefully

Try 50 or 100 branches next:

```powershell
python scripts\run_stage2c_inventory.py --catalog artifacts\stage2b-5000\drug_catalog.json --pharmacies 100 --output artifacts\stage2c-100
```

Do **not** jump straight to 1,000 inventory branches yet. With thousands of SKUs per
branch this can create millions of Python objects and batch rows. The next scale-hardening
step will make the exporter chunked/streaming before 1,000-branch inventory is an
acceptance target.
