# Stage 7B lint hotfix — v0.23.1

This hotfix fixes two Ruff findings from v0.23.0 without changing Stage 7B behavior:

- Sorts the simulation package imports deterministically.
- Imports `Iterable` from `collections.abc` for modern Python compatibility.

No data-generation, calibration, provenance, or acceptance logic changed.
