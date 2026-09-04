"""Run the complete visible Stage 2D checkpoint: streaming scale export + FEFO demo."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def find_catalog() -> Path:
    candidates = (
        Path("artifacts/stage2b-5000/drug_catalog.json"),
        Path("artifacts/stage2b-1000/drug_catalog.json"),
        Path("artifacts/stage2b/drug_catalog.json"),
    )
    return next((path for path in candidates if path.exists()), candidates[-1])


def main() -> int:
    catalog = find_catalog()
    if not catalog.exists():
        print("STAGE_2D_STATUS=FAIL")
        print("No Stage 2B catalog found. Run Stage 2B first.")
        return 2

    scale_command = [
        sys.executable,
        "scripts/run_stage2d_scale.py",
        "--catalog",
        str(catalog),
        "--pharmacies",
        "25",
        "--branches-per-part",
        "5",
        "--output",
        "artifacts/stage2d",
    ]
    if subprocess.call(scale_command) != 0:
        return 2

    print("\n--- FEFO DEMO ---\n", flush=True)
    fefo_command = [
        sys.executable,
        "scripts/run_stage2d_fefo_demo.py",
        "--batch-dir",
        "artifacts/stage2d/batches",
    ]
    if subprocess.call(fefo_command) != 0:
        return 2

    print("\nSTAGE_2D_STATUS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
