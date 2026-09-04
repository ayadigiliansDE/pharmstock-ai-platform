PharmStock V2 — Stage 2D patch

Extract the CONTENTS of this ZIP directly into your existing:
D:\Data_Engineer_Work_With_VSCode\Projects\pharmstock-ai-platform-v2

Choose Replace/Overwrite when Windows asks.
The patch contains no .venv and no artifacts directory, so your local environment and generated
Stage 2A/2B/2C data remain in place.

Then run in the activated PowerShell environment:
  pip install -e ".[dev]"
  pytest
  ruff check .
  python scripts\run_checkpoint.py 2d

Expected pytest checkpoint: 87 passed
Expected final marker: STAGE_2D_STATUS=PASS

See docs\STAGE_02D_LOCAL_RUN.md for the large-network scale command.
