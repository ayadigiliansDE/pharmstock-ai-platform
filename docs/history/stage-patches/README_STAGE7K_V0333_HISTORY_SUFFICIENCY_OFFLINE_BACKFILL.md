# Stage 7K v0.33.3 — Historical Sufficiency + Zero-Cost Offline ML Backfill

This hotfix is cumulative on top of v0.33.2.

## Root cause fixed

The operational Stage 7E acceptance history is intentionally short, while the
scientific Stage 7K demand model requires a 28-day lag plus a 30-day future target.
That makes a short observed window incapable of producing valid demand training
rows. The old query correctly returned zero demand rows, but the launcher did not
provide a scientifically valid fallback.

## New behavior

- Measures observed BigQuery history coverage first.
- Uses observed warehouse history directly only when at least 90 distinct days are
  available.
- Otherwise creates a 365-day, zero-cost, local, synthetic-calibrated offline
  training store from observed product and branch-product aggregates.
- The backfilled period is explicitly tagged
  `SYNTHETIC_CALIBRATED_OFFLINE_BACKFILL`; it is never represented as observed data.
- Demand history contains exact 28-day lag burn-in and complete 1/7/14/30-day
  future targets.
- Stockout history uses explicit inventory depletion, replenishment queues,
  supplier reliability and future observed-in-simulation stockout labels.
- Reorder replay now preserves outstanding inbound units rather than forcing them
  to zero.
- Local Parquet training histories are written only under
  `artifacts/stage7k/offline_training_store/`.
- BigQuery remains READ ONLY. No cloud writes, no billing, no table copies.

## Apply

Extract this ZIP directly into the project root:

`D:\Data_Engineer_Work_With_VSCode\Projects\pharmstock-ai-platform-v2`

## Validate

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest tests\test_stage7k_ml.py -q
```

Expected tests: `18 passed`.

No dependency changed in this hotfix, so reuse the existing ML image:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7k.py --execute --no-build
```

Expected log should explicitly show the observed history days and, if the
warehouse window is short, the local 365-day backfill provenance before training.
