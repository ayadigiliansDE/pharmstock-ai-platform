# Stage 2F — Local Run Guide (Windows / PowerShell)

Stage 2F requires a completed `artifacts\stage2e` dataset.

## 1. Install the updated editable package

```powershell
pip install -e ".[dev]"
```

Confirm the checkpoint version:

```powershell
python -c "import pharmstock; print(pharmstock.__version__)"
```

Expected:

```text
0.10.0
```

## 2. Run acceptance checks

```powershell
pytest
ruff check .
```

The Stage 2F patch contains 114 tests in total. Expected pytest summary:

```text
114 passed
```

Ruff should report:

```text
All checks passed!
```

## 3. Run the visible checkpoint

```powershell
python scripts\run_checkpoint.py 2f
```

The run should finish with:

```text
STAGE_2F_STATUS=PASS
```

Counts such as ordered/received units depend on the exact Stage 2E output on your machine.

## 4. Inspect the generated files

Open this folder:

```text
artifacts\stage2f
```

Important outputs:

```text
supplier_master.csv
purchase_orders\part-*.csv
purchase_order_lines\part-*.csv
goods_receipts\part-*.csv
goods_receipt_lines\part-*.csv
restock_movements\part-*.csv
procurement_backlog.csv
branch_procurement_kpis.csv
ending_inventory\part-*.csv
ending_batches\part-*.csv
procurement_manifest.json
_SUCCESS
```

Recommended Excel inspection order:

1. `branch_procurement_kpis.csv`
2. `purchase_orders\part-00001.csv`
3. `purchase_order_lines\part-00001.csv`
4. `goods_receipt_lines\part-00001.csv`
5. `restock_movements\part-00001.csv`
6. `procurement_backlog.csv`

## 5. What you should observe

For a low-stock product, trace this chain:

```text
Stage 2E ending_inventory
    ↓
Purchase Order Line
    ↓
Goods Receipt Line
    ↓
PROC-* batch
    ↓
Positive restock movement
    ↓
Stage 2F ending_inventory quantity increased
```

No monetary fields are generated in this stage.
