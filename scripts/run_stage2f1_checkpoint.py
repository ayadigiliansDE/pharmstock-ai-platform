"""Run the visible Stage 2F.1 supplier-network scaling checkpoint."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    stage2e = Path("artifacts/stage2e")
    if not (stage2e / "_SUCCESS").exists():
        print("STAGE_2F1_STATUS=FAIL")
        print("Stage 2E _SUCCESS not found. Run checkpoint 2e first.")
        return 2
    return subprocess.call(
        [
            sys.executable,
            "scripts/run_stage2f1_supplier_network.py",
            "--stage2e",
            str(stage2e),
            "--seed",
            "20260822",
            "--output",
            "artifacts/stage2f1",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
