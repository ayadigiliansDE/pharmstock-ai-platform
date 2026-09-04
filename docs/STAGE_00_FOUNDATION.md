# Stage 0 — Foundation

## Objective

Create a clean project shell before introducing platform technologies.

## Why `src/pharmstock/`?

Using a `src` layout makes Python import the installed project package rather than accidentally importing files from the repository root. This reduces hidden import/path bugs and makes tests closer to production execution.

## Why `pyproject.toml`?

It is the central Python project configuration file. At Stage 0 it declares:

- package name and Python version
- package discovery rules
- development tools (pytest, ruff)
- pytest settings
- lint settings

Runtime dependencies are intentionally absent for now. Kafka/Spark/ML dependencies will be added only when their stage starts.

## Why `.env.example`?

It documents configuration names without storing real secrets. The real `.env` is ignored by Git.

## Why empty layer folders now?

They communicate architectural boundaries. Implementation enters them only when the corresponding stage begins.

## Stage 0 acceptance criteria

- Original ZIP remains unchanged.
- V2 exists in a separate directory.
- `pip install -e ".[dev]"` installs the package and dev tools.
- `pytest` passes.
- `ruff check .` passes.
- Target architecture is documented.
- No production technology has been prematurely implemented.
