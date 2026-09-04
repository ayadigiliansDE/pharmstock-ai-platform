# Stage 7B — Local Run

From the repository root on Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,gcp,analytics]"
.\.venv\Scripts\python.exe -c "import pharmstock; print(pharmstock.__version__)"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 7b
```

Expected package version:

```text
0.23.1
```

Default acceptance profile:

```text
Profile:                    acceptance
CAPMAS population 2024:     105,914,499
CAPMAS general pharmacies:  86,741
Modeled branches:           5,000
Governorates covered:       27 / 27
Provenance:                 SYNTHETIC_CALIBRATED
Real pharmacy identities:   NO
Cloud mutation:             NO
STAGE_7B_STATUS=PASS
```

Run a fast 27-branch profile:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7b_network.py --profile dev
```

Generate the national reference scale only when the machine has enough time/storage:

```powershell
.\.venv\Scripts\python.exe scripts\run_stage7b_network.py `
  --profile full_market `
  --output artifacts\stage7b-full-market
```

Stage 7B performs no cloud mutation.
