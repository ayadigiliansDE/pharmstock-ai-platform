"""Stage 5C local-safe dbt project checkpoint.

This command parses the dbt project locally and never executes warehouse models.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from pharmstock.analytics.dbt_stage import (
    DBT_PROFILES_RELATIVE,
    DBT_PROJECT_RELATIVE,
    inspect_stage5c_project,
    write_local_stage5c_plan,
)


def _dbt_executable() -> str | None:
    executable = "dbt.exe" if os.name == "nt" else "dbt"
    beside_python = Path(sys.executable).parent / executable
    if beside_python.is_file():
        return str(beside_python)
    return shutil.which("dbt")


def main() -> None:
    project_root = DBT_PROJECT_RELATIVE
    profiles_root = DBT_PROFILES_RELATIVE
    stage5b_root = Path("artifacts/stage5b")
    output_root = Path("artifacts/stage5c")

    plan = write_local_stage5c_plan(output_root, project_root, stage5b_root)
    readiness = inspect_stage5c_project(project_root, stage5b_root)
    dbt = _dbt_executable()

    print("=== PharmStock V2 / Stage 5C dbt Analytics Local Checkpoint ===")
    print(f"Project files ready:      {'YES' if readiness.project_files_ready else 'NO'}")
    print(f"dbt installed:            {'YES' if readiness.dbt_installed else 'NO'}")
    print(f"Project configured:       {'YES' if readiness.project_configured else 'NO'}")
    print(
        "Stage 5B cloud report:   "
        f"{'YES' if readiness.stage5b_cloud_report_present else 'NO'}"
    )
    print(f"Staging models:           {readiness.staging_model_count}")
    print(f"Intermediate models:      {readiness.intermediate_model_count}")
    print(f"Gold models:              {readiness.gold_model_count}")
    print(f"Singular data tests:      {readiness.data_test_count}")
    print("Cloud mutation performed: NO")

    if not readiness.project_files_ready:
        raise SystemExit("Stage 5C dbt project contract is incomplete.")
    if not readiness.dbt_installed or dbt is None:
        raise SystemExit('Install dbt first: pip install -e ".[analytics]"')

    command = [
        dbt,
        "parse",
        "--project-dir",
        str(project_root),
        "--profiles-dir",
        str(profiles_root),
        "--no-partial-parse",
    ]
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)

    (output_root / "_SUCCESS").write_text("STAGE_5C_STATUS=PASS\n", encoding="utf-8")
    print("\ndbt parse:                PASS")
    print(f"Gold target dataset:       {plan['catalog']['gold_dataset']}")
    print("STAGE_5C_STATUS=PASS")


if __name__ == "__main__":
    main()
