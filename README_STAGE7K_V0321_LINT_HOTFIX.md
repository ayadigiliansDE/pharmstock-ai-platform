# Stage 7K v0.32.1 Lint Hotfix

Fixes Ruff F541 only.

Changed files:
- `ml/stage7k/train.py`
- `scripts/run_stage7k.py`

Changes:
- Removed unnecessary `f` prefixes from static `print()` strings.
- No ML logic changes.
- No BigQuery logic changes.
- No MLflow/registry/serving changes.
- No storage policy changes.

Apply by extracting this archive directly into the PharmStock project root.
