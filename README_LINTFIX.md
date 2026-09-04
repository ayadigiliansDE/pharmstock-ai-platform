# Stage 2D lint hotfix — v0.8.1

Apply this patch over the existing `pharmstock-ai-platform-v2` project.
It only changes the five Ruff findings reported on Windows plus the package patch version.

Changes:
- `DomainEvent` now uses Python 3.14 / PEP 695 generic class syntax.
- Removed unused `Decimal` import from simulation/inventory.py.
- Removed unused `defaultdict`, `Iterable`, and `asdict` imports from simulation/network.py.
- Version bumped from 0.8.0 to 0.8.1.

Run in the existing activated venv:

```powershell
pip install -e ".[dev]"
pytest
ruff check .
python scripts\run_checkpoint.py 2d
```

Expected lint result:

```text
All checks passed!
```
