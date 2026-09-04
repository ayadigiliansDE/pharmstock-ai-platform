# Local Run Guide — Watch PharmStock V2 Grow Stage by Stage


## Windows timezone dependency

PharmStock uses IANA timezone names such as `Africa/Cairo`. Windows does not
ship the IANA timezone database in the same way as many Unix-like systems, so
`tzdata==2026.3` is a required runtime dependency of the project. It is installed
automatically by:

```powershell
pip install -e ".[dev]"
```

If you upgraded from Stage 2A version 0.5.0, reinstall the editable package once:

```powershell
python -m pip install -e ".[dev]"
pytest
```

A quick repair for an already-created environment is:

```powershell
python -m pip install tzdata==2026.3
pytest
```

Expected result for this checkpoint: all tests pass.

This guide is a permanent part of the V2 workflow. Every new stage must add a runnable
checkpoint, the exact command to run it, and the output you should expect to see.

## 1. One-time setup on Windows 10/11

Open **PowerShell** in the project folder — the folder that contains `pyproject.toml`.

Check that Python 3.14 is installed:

```powershell
py -3.14 --version
```

Expected shape:

```text
Python 3.14.x
```

Create a dedicated virtual environment:

```powershell
py -3.14 -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

Your prompt should now start with something similar to:

```text
(.venv) PS C:\...\pharmstock-ai-platform-v2>
```

Upgrade pip and install the current project in editable mode:

```powershell
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

`-e` means **editable install**: when you change Python source code in this project,
you do not have to reinstall the package after every edit.

## 2. Verify the source checkpoint before running a demo

Run all tests:

```powershell
pytest
```

For the previous Stage 2C checkpoint the expected result was:

```text
72 passed
```

Run linting:

```powershell
ruff check .
```

## 3. Replay Stage 1C — single pharmacy transaction flow

This lets you see what the system could do before the large simulator existed:

```powershell
python scripts\run_checkpoint.py 1c
```

You should see the sale reduce stock and a reorder decision/event become visible.

## 4. Run Stage 2A as a small visual preview

Run 25 pharmacies first so the generated files are easy to inspect:

```powershell
python scripts\run_checkpoint.py 2a
```

Equivalent explicit command:

```powershell
python scripts\run_stage2a_network.py --pharmacies 25 --seed 20260822 --output artifacts\stage2a-25
```

Expected final marker:

```text
STAGE_2A_STATUS=PASS
```

Open these generated files:

```text
artifacts\stage2a-25\pharmacy_organizations.csv
artifacts\stage2a-25\pharmacy_branches.csv
artifacts\stage2a-25\network_summary.json
```

The CSV files can be opened directly in Excel.

## 5. Scale the same code to 1,000 pharmacies

No Python source-code change is required:

```powershell
python scripts\run_stage2a_network.py --pharmacies 1000 --seed 20260822 --output artifacts\stage2a-1000
```

With the Stage 2A default seed, the current checkpoint produces:

```text
Organizations:     149
Pharmacy branches: 1,000
Governorates used: 27 / 27
STAGE_2A_STATUS=PASS
```

The exact organization/scale mixture is deterministic for a fixed seed. Change the seed
to create a different, but valid, synthetic network:

```powershell
python scripts\run_stage2a_network.py --pharmacies 1000 --seed 99 --output artifacts\stage2a-seed99
```

## 6. How to compare the evolution of the project

Run the old checkpoint, then the new one:

```powershell
python scripts\run_checkpoint.py 1c
python scripts\run_checkpoint.py 2a
```

Conceptually you are seeing this evolution:

```text
Stage 1C
1 Pharmacy + Product -> Sale -> Inventory change -> Reorder event

Stage 2A
CAPMAS geography weights -> Organizations -> 1,000 Pharmacy Branches -> CSV/JSON artifacts
```

Starting with Stage 2A, every future checkpoint will extend this same workflow rather
than silently replacing it.

## 7. If PowerShell blocks venv activation

You can avoid changing the execution policy and run the environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts\run_stage2a_network.py --pharmacies 25
```

## 8. Reset generated output

Generated simulation files are disposable and are ignored by Git. To regenerate them:

```powershell
Remove-Item -Recurse -Force artifacts\stage2a-25
python scripts\run_stage2a_network.py --pharmacies 25 --output artifacts\stage2a-25
```

Source code is not deleted by this command; only generated output is rebuilt.


## Stage 2B — real drug catalog
See `docs/STAGE_02B_LOCAL_RUN.md`. The shortest live checkpoint is:

```powershell
python scripts\run_checkpoint.py 2b
```


## Stage 2C — branch assortment and inventory
See `docs/STAGE_02C_LOCAL_RUN.md`. Shortest command:

```powershell
python scripts\run_checkpoint.py 2c
```

This joins the pharmacy network to the largest Stage 2B catalog already present under `artifacts/`.


## Stage 2D — scale hardening and FEFO
See `docs/STAGE_02D_LOCAL_RUN.md`. Shortest command:

```powershell
python scripts\run_checkpoint.py 2d
```

The current Stage 2D test-suite target on the flat v0.8.1 checkpoint is:

```text
86 passed
```


## Stage 2E — demand and unit sales
See `docs/STAGE_02E_LOCAL_RUN.md`. Shortest command after Stage 2D has passed:

```powershell
python scripts\run_checkpoint.py 2e
```

The Stage 2E patch adds 14 tests to the v0.8.1 Windows checkpoint, so the expected local total is:

```text
100 passed
```


## Stage 2F — procurement and replenishment
See `docs/STAGE_02F_LOCAL_RUN.md`. Shortest command after Stage 2E has passed:

```powershell
python scripts\run_checkpoint.py 2f
```

The Stage 2F checkpoint target is:

```text
114 passed
ruff: All checks passed!
STAGE_2F_STATUS=PASS
```


## Stage 2F.1 — scalable supplier network
See `docs/STAGE_02F1_LOCAL_RUN.md`. After Stage 2E exists, run:

```powershell
python scripts\run_checkpoint.py 2f1
```

Checkpoint targets:

```text
version: 0.10.1
123 passed
ruff: All checks passed!
153 synthetic suppliers
STAGE_2F1_STATUS=PASS
```

Stage 2F remains runnable separately with `python scripts\run_checkpoint.py 2f`.

## Stage 3B — simulator event streaming
See `docs/STAGE_03B_LOCAL_RUN.md`. With Kafka healthy and Stage 2E/2F.1 artifacts present:

```powershell
python scripts\run_checkpoint.py 3b
```

Checkpoint targets:

```text
version: 0.12.0
142 passed
ruff: All checks passed!
STAGE_3B_STATUS=PASS
```

## Stage 3C — durable consumer processing and idempotency
See `docs/STAGE_03C_LOCAL_RUN.md`. With Kafka healthy and Stage 2E/2F.1 artifacts present:

```powershell
python scripts\run_checkpoint.py 3c
```

Checkpoint targets:

```text
version: 0.13.0
150 passed
ruff: All checks passed!
processed: 100
duplicates: 100
failed -> DLQ: 2
STAGE_3C_STATUS=PASS
```

The checkpoint deliberately publishes the same 100 deterministic valid event IDs twice, plus one forced handler failure and one malformed raw message. The durable inbox must keep only one processed row per valid `event_id`.


## Stage 4A — Spark Structured Streaming
See `docs/STAGE_04A_LOCAL_RUN.md`. Shortest checkpoint after Kafka is recreated with the
dual-listener config:

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 4a
```

The Stage 4A test target is `162 passed`.

## Stage 4B — Silver normalization
See `docs/STAGE_04B_LOCAL_RUN.md`. Run only after Stage 4A has passed on the current Kafka broker:

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 4b
```

Checkpoint targets:

```text
version: 0.15.0
174 passed
ruff: All checks passed!
Silver event_id values unique
Replay duplicates audited
Event-ID conflicts audited
Invalid payloads audited
STAGE_4B_STATUS=PASS
```


## Stage 5A — BigQuery warehouse foundation
See `docs/STAGE_05A_LOCAL_RUN.md`. The local checkpoint is cloud-safe:

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 5a
```

It validates Stage 4B Silver with Spark, writes BigQuery-ready Parquet, and generates schema
JSON/DDL/load-plan artifacts without contacting Google Cloud.


## Stage 5B
```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 5b
```
This is local-safe and performs no cloud mutation. See `docs/STAGE_05B_LOCAL_RUN.md` for the optional live BigQuery path.


## Stage 5C

Install `.[dev,gcp,analytics]`, set the BigQuery/dbt environment variables, then run `python scripts/run_checkpoint.py 5c`. Use `scripts/run_stage5c_dbt.py` without `--execute` for a parse-only dry run; use `--execute` only for the explicit BigQuery build.


## Stage 5D — Master dimensions

The analytics warehouse now has an explicit `pharmstock_master` layer feeding dbt dimensions
`dim_product`, `dim_branch`, and `dim_supplier`. Product origin is U.S. openFDA; pharmacy and
supplier entities remain synthetic and are labeled as such.

## Stage 6B — Power BI Desktop build kit

After `STAGE_6A_CLOUD_STATUS=PASS`, set `PHARMSTOCK_BQ_PROJECT` and
`PHARMSTOCK_PBI_DATASET`, then run:

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 6b
```

The checkpoint generates deterministic Desktop authoring assets and performs no Desktop
or cloud mutation. See `docs/STAGE_06B_LOCAL_RUN.md`.

## Stage 7A — Egyptian Pharmaceutical Master

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 7a
```

The first run downloads and caches the CC0 Egyptian-market product snapshot. The checkpoint builds
an Egypt-oriented medicine master, EGP retail-price observations, a reject/audit file, and an EDA
verification queue. It performs no cloud mutation. See `docs/STAGE_07A_LOCAL_RUN.md`.

## Stage 7B — production-like pharmacy network

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 7b
```

The default acceptance profile generates 5,000 fictional branches across all 27 governorates.
See `STAGE_07B_LOCAL_RUN.md` for dev/full-market profiles and acceptance expectations.

## Stage 7C — financial calibration

After Stage 7A and 7B both pass:

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 7c
```

This creates product economics, branch commercial policy, sample reconciled financial lines,
and auditable assumptions. It performs no cloud mutation.

## Stage 7D — On-Prem PostgreSQL Operational / POS Database

Prerequisites: Stage 7A, 7B and 7C must already show PASS, and Docker Desktop must be running.

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 7d
```

The first run downloads the pinned PostgreSQL 18.6 image if needed, starts local port 5433, loads
master/commercial state and verifies CDC readiness. See `STAGE_07D_LOCAL_RUN.md` for inspection and
stop/start commands.
