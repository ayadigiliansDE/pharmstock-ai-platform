"""Stage 6A local-safe Power BI serving checkpoint."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from pharmstock.analytics.dbt_stage import DBT_PROFILES_RELATIVE, DBT_PROJECT_RELATIVE
from pharmstock.analytics.powerbi_stage import (
    DEFAULT_PBI_DATASET,
    inspect_stage6a,
    write_stage6a_local_artifacts,
)


def _dbt_executable() -> str | None:
    executable = "dbt.exe" if os.name == "nt" else "dbt"
    beside_python = Path(sys.executable).parent / executable
    if beside_python.is_file():
        return str(beside_python)
    return shutil.which("dbt")


def main() -> None:
    output = Path("artifacts/stage6a")
    project = os.getenv("PHARMSTOCK_BQ_PROJECT")
    dataset = os.getenv("PHARMSTOCK_PBI_DATASET", DEFAULT_PBI_DATASET)
    report = write_stage6a_local_artifacts(output, project_id=project, dataset_id=dataset)
    readiness = inspect_stage6a()
    dbt = _dbt_executable()

    print("=== PharmStock V2 / Stage 6A Power BI Serving Local Checkpoint ===")
    print(f"Project files ready:      {'YES' if readiness.project_files_ready else 'NO'}")
    print(
        "Stage 5D dimensions:      "
        f"{'YES' if readiness.stage5d_dimensions_report_present else 'NO'}"
    )
    print(f"Project configured:       {'YES' if readiness.project_configured else 'NO'}")
    print(f"dbt installed:            {'YES' if dbt else 'NO'}")
    print(f"Power BI serving models:  {readiness.pbi_model_count}")
    print(f"Semantic relationships:   {readiness.relationship_count}")
    print(f"Explicit DAX measures:    {readiness.measure_count}")
    print("Recommended mode:         Import")
    print("Monetary measures added:  NO")
    print("Cloud mutation performed: NO")

    if not readiness.project_files_ready:
        raise SystemExit("Stage 6A serving model contract is incomplete")
    if not readiness.stage5d_dimensions_report_present:
        raise SystemExit("Stage 6A requires completed Stage 5D dimensions")
    if dbt is None:
        raise SystemExit('Install analytics dependencies: pip install -e ".[analytics]"')

    command = [
        dbt,
        "parse",
        "--project-dir",
        str(DBT_PROJECT_RELATIVE),
        "--profiles-dir",
        str(DBT_PROFILES_RELATIVE),
        "--no-partial-parse",
    ]
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)

    (output / "_SUCCESS").write_text("STAGE_6A_STATUS=PASS\n", encoding="utf-8")
    print(f"\nPower BI dataset target:  {report['powerbi_dataset']}")
    print("dbt parse:                PASS")
    print("STAGE_6A_STATUS=PASS")


if __name__ == "__main__":
    main()
