"""Run the visible Stage 2F checkpoint against completed Stage 2E output."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    stage2e = Path("artifacts/stage2e")
    if not (stage2e / "_SUCCESS").exists():
        print("STAGE_2F_STATUS=FAIL")
        print("Stage 2E _SUCCESS not found. Run checkpoint 2e first.")
        return 2
    return subprocess.call(
        [
            sys.executable,
            "scripts/run_stage2f_procurement.py",
            "--stage2e",
            str(stage2e),
            "--seed",
            "20260822",
            "--output",
            "artifacts/stage2f",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
