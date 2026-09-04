"""Small local checkpoint launcher so each development stage can be observed directly."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def checkpoint_command(checkpoint: str) -> list[str]:
    if checkpoint == "1c":
        return [sys.executable, "scripts/demo_stage1c_flow.py"]
    if checkpoint == "2a":
        return [sys.executable, "scripts/run_stage2a_network.py", "--pharmacies", "25"]
    if checkpoint == "2b":
        return [sys.executable, "scripts/run_stage2b_catalog.py", "--records", "100"]
    if checkpoint == "2d":
        return [sys.executable, "scripts/run_stage2d_checkpoint.py"]
    if checkpoint == "2e":
        return [sys.executable, "scripts/run_stage2e_checkpoint.py"]
    if checkpoint == "2f":
        return [sys.executable, "scripts/run_stage2f_checkpoint.py"]
    if checkpoint == "2f1":
        return [sys.executable, "scripts/run_stage2f1_checkpoint.py"]
    if checkpoint == "3a":
        return [sys.executable, "scripts/run_stage3a_checkpoint.py"]
    if checkpoint == "3b":
        return [sys.executable, "scripts/run_stage3b_checkpoint.py"]
    if checkpoint == "3c":
        return [sys.executable, "scripts/run_stage3c_checkpoint.py"]
    if checkpoint == "4a":
        return [sys.executable, "scripts/run_stage4a_checkpoint.py"]
    if checkpoint == "4b":
        return [sys.executable, "scripts/run_stage4b_checkpoint.py"]
    if checkpoint == "5a":
        return [sys.executable, "scripts/run_stage5a_checkpoint.py"]
    if checkpoint == "5b":
        return [sys.executable, "scripts/run_stage5b_checkpoint.py"]
    if checkpoint == "5c":
        return [sys.executable, "scripts/run_stage5c_checkpoint.py"]
    if checkpoint == "5d":
        return [sys.executable, "scripts/run_stage5d_checkpoint.py"]
    if checkpoint == "6a":
        return [sys.executable, "scripts/run_stage6a_checkpoint.py"]
    if checkpoint == "6b":
        return [sys.executable, "scripts/run_stage6b_checkpoint.py"]
    if checkpoint == "7a":
        return [sys.executable, "scripts/run_stage7a_egypt_master.py"]
    if checkpoint == "7b":
        return [sys.executable, "scripts/run_stage7b_network.py"]
    if checkpoint == "7c":
        return [sys.executable, "scripts/run_stage7c_financial.py"]
    if checkpoint == "7d":
        return [sys.executable, "scripts/run_stage7d_onprem.py"]
    if checkpoint == "7e":
        return [sys.executable, "scripts/run_stage7e_history.py"]
    if checkpoint == "7f":
        return [sys.executable, "scripts/run_stage7f_cdc.py"]
    if checkpoint == "7g":
        return [sys.executable, "scripts/run_stage7g_rebuild.py"]
    if checkpoint == "7h":
        return [sys.executable, "scripts/run_stage7h_checkpoint.py"]
    if checkpoint == "7i":
        return [sys.executable, "scripts/run_stage7i_cdc.py"]
    if checkpoint == "7j":
        return [sys.executable, "scripts/run_stage7j.py"]
    if checkpoint == "7k":
        return [sys.executable, "scripts/run_stage7k.py"]
    if checkpoint == "7k5":
        return [sys.executable, "scripts/run_stage7k5.py"]
    if checkpoint == "7l":
        return [sys.executable, "scripts/run_stage7l.py"]
    if checkpoint == "7m":
        return [sys.executable, "scripts/run_stage7m.py"]
    if checkpoint == "7n":
        return [sys.executable, "scripts/run_stage7n_powerbi.py"]
    if checkpoint == "2c":
        candidates = (
            Path("artifacts/stage2b-5000/drug_catalog.json"),
            Path("artifacts/stage2b/drug_catalog.json"),
        )
        catalog = next((path for path in candidates if path.exists()), candidates[-1])
        return [
            sys.executable,
            "scripts/run_stage2c_inventory.py",
            "--catalog",
            str(catalog),
            "--pharmacies",
            "25",
        ]
    raise ValueError(f"unknown checkpoint: {checkpoint}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a visible PharmStock development checkpoint")
    parser.add_argument(
        "checkpoint",
        choices=(
            "1c", "2a", "2b", "2c", "2d", "2e", "2f", "2f1",
            "3a", "3b", "3c", "4a", "4b", "5a", "5b", "5c", "5d",
            "6a", "6b", "7a", "7b", "7c", "7d", "7e", "7f", "7g", "7h", "7i",
            "7j", "7k", "7k5", "7l", "7m", "7n",
        ),
    )
    args = parser.parse_args()
    raise SystemExit(subprocess.call(checkpoint_command(args.checkpoint)))


if __name__ == "__main__":
    main()
