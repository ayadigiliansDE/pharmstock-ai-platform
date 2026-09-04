# Stage 3C Patch — v0.13.0

Apply this ZIP directly over the Stage 3B project root and replace existing files.
The patch is flat: `pyproject.toml`, `src/`, `scripts/`, `tests/`, and `docs/` are at the ZIP root.

Windows verification:

```powershell
pip install -e ".[dev]"
python -c "import pharmstock; print(pharmstock.__version__)"
pytest
ruff check .
docker compose -f infra/docker/docker-compose.kafka.yml ps
python scripts\run_checkpoint.py 3c
```

Targets:

```text
version: 0.13.0
150 passed
ruff: All checks passed!
STAGE_3C_STATUS=PASS
```
