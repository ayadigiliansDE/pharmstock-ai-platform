# Stage 4A Python 3.10 Spark Runtime Hotfix

Fixes the Spark-container startup failure caused by importing `datetime.UTC`, which is unavailable in Python 3.10.

Changes:
- Spark job uses `timezone.utc` instead of the Python 3.11+ `datetime.UTC` alias.
- Ruff checks `spark/jobs/*.py` using a Python 3.10 per-file target while the application remains Python 3.14.
- Adds a regression test that parses the Spark job as Python 3.10 syntax and rejects reintroduction of `from datetime import UTC`.

No Stage 4A business logic or version number changes. Version remains 0.14.0.
