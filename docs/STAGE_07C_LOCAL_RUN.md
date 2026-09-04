# Stage 7C local run

Prerequisites: Stage 7A and Stage 7B must both have `_SUCCESS` artifacts.

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 7c
```

Expected final marker:

```text
STAGE_7C_STATUS=PASS
```

The default checkpoint performs no cloud mutation.
