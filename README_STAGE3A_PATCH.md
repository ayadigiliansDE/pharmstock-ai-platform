# PharmStock V2 — Stage 3A Patch

Flat patch for applying Stage 3A directly over the validated Stage 2F.1 / v0.10.1 project.
It does not contain `.venv` or generated `artifacts`.

After extraction over the project root:

```powershell
pip install -e ".[dev]"
python -c "import pharmstock; print(pharmstock.__version__)"
pytest
ruff check .
docker compose -f infra/docker/docker-compose.kafka.yml up -d
python scripts/run_stage3a_topics.py
python scripts/run_checkpoint.py 3a
```

See `docs/STAGE_03A_LOCAL_RUN.md` for the manual two-terminal producer/consumer exercise.
