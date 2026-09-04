# Stage 3A lint hotfix

This flat patch fixes only Ruff findings in Stage 3A v0.11.0.

Changed files:
- scripts/run_checkpoint.py
- scripts/run_stage3a_checkpoint.py
- scripts/run_stage3a_producer.py
- scripts/run_stage3a_topics.py

No business logic or version changes are included.

After extracting over the project root, run:

```powershell
pytest
ruff check .
```

Expected:
- 132 tests passed
- All checks passed!
