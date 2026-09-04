# Stage 2D — Windows / PowerShell local run

Run from the project root with the Python 3.14 virtual environment activated.

## 1. Install the updated checkpoint

```powershell
pip install -e ".[dev]"
```

## 2. Acceptance tests

```powershell
pytest
ruff check .
```

Expected test result for Stage 2D:

```text
86 passed
```

## 3. Small visible Stage 2D checkpoint

This uses the largest Stage 2B catalog already present and generates 25 branches as five branch
partitions, then demonstrates FEFO:

```powershell
python scripts\run_checkpoint.py 2d
```

Expected final markers:

```text
STAGE_2D_SCALE_STATUS=PASS
STAGE_2D_FEFO_STATUS=PASS
STAGE_2D_STATUS=PASS
```

Inspect:

```text
artifacts\stage2d\inventory\
artifacts\stage2d\batches\
artifacts\stage2d\branch_assortment_summary.csv
artifacts\stage2d\inventory_manifest.json
```

## 4. Scale test

After the small checkpoint passes, the same implementation can be run for a large network. Your
existing 5,000-source-record Stage 2B catalog is at:

```text
artifacts\stage2b-5000\drug_catalog.json
```

Example 1,000-branch command:

```powershell
python scripts\run_stage2d_scale.py `
  --catalog artifacts\stage2b-5000\drug_catalog.json `
  --pharmacies 1000 `
  --branches-per-part 25 `
  --output artifacts\stage2d-1000
```

This command writes completed branch chunks as it goes instead of retaining the complete network
inventory dataset in memory. Large runs can still consume substantial disk space because the output
itself can contain millions of rows. In the Stage 2D acceptance run, 25 branches with a 9,042-SKU
catalog produced about 34 MB of CSV output; a 1,000-branch run under a similar distribution can be
roughly gigabyte-scale, so check free disk space before starting it.

## 5. Replay FEFO against the large run

```powershell
python scripts\run_stage2d_fefo_demo.py --batch-dir artifacts\stage2d-1000\batches
```
