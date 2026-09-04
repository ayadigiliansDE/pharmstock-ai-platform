# PharmStock Stage 7B Patch — v0.23.0

Stage 7B adds the production-like Egyptian pharmacy network used by the next pricing,
transaction, CDC, ML, and AI stages.

The default acceptance run creates 5,000 fictional branches across all 27 governorates,
calibrated to CAPMAS 2024 population/urban-rural statistics and the national reference of
86,741 general pharmacies. Business identities and operating attributes remain explicitly
`SYNTHETIC_CALIBRATED`.

Run:

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 7b
```

See `docs/STAGE_07B_PRODUCTION_PHARMACY_NETWORK.md` and `docs/STAGE_07B_LOCAL_RUN.md`.
