"""Run the visible Stage 2E checkpoint against the completed Stage 2D dataset."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    stage2d = Path("artifacts/stage2d")
    if not (stage2d / "_SUCCESS").exists():
        print("STAGE_2E_STATUS=FAIL")
        print("Stage 2D _SUCCESS not found. Run checkpoint 2d first.")
        return 2
    return subprocess.call(
        [
            sys.executable,
            "scripts/run_stage2e_demand.py",
            "--stage2d",
            str(stage2d),
            "--start-date",
            "2026-08-22",
            "--days",
            "7",
            "--seed",
            "20260822",
            "--output",
            "artifacts/stage2e",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
