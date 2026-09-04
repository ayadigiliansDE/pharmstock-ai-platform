"""Stage 6B local-safe Power BI Desktop build-kit checkpoint."""

from __future__ import annotations

import os
from pathlib import Path

from pharmstock.analytics.powerbi_desktop_stage import (
    DEFAULT_PBI_DATASET,
    inspect_stage6b,
    write_stage6b_build_kit,
)


def main() -> None:
    project = os.getenv("PHARMSTOCK_BQ_PROJECT", "").strip()
    dataset = os.getenv("PHARMSTOCK_PBI_DATASET", DEFAULT_PBI_DATASET).strip()
    if not project:
        raise SystemExit("Set PHARMSTOCK_BQ_PROJECT before Stage 6B")

    readiness = inspect_stage6b()
    print("=== PharmStock V2 / Stage 6B Power BI Desktop Build Kit ===")
    print(f"Stage 6A cloud success:   {'YES' if readiness.stage6a_cloud_success else 'NO'}")
    print(f"Semantic contract:        {'YES' if readiness.semantic_contract_present else 'NO'}")
    print(f"Measure library:          {'YES' if readiness.measure_library_present else 'NO'}")
    print(f"Tables to load:           {readiness.table_count}")
    print(f"Relationships to create:  {readiness.relationship_count}")
    print(f"Explicit DAX measures:    {readiness.measure_count}")
    print(f"Report pages specified:   {readiness.report_page_count}")
    print("Recommended storage mode: Import")
    print("Desktop mutation:         NO")

    if not readiness.stage6a_cloud_success:
        raise SystemExit("Stage 6B requires STAGE_6A_CLOUD_STATUS=PASS first")
    if not readiness.semantic_contract_present or not readiness.measure_library_present:
        raise SystemExit("Stage 6B source-controlled Power BI assets are incomplete")

    output = Path("artifacts/stage6b")
    report = write_stage6b_build_kit(output, project_id=project, dataset_id=dataset)
    (output / "_BUILD_KIT_SUCCESS").write_text(
        "STAGE_6B_BUILD_KIT_STATUS=PASS\n", encoding="utf-8"
    )

    print("\nGenerated build kit:")
    for name in (
        "desktop_build_manifest.json",
        "relationships.csv",
        "measures.csv",
        "measures.dax",
        "dashboard_spec.json",
        "bigquery_connection.m",
        "desktop_acceptance_checklist.md",
    ):
        print(f"  {output / name}")
    print(f"\nPower BI dataset:         {report['dataset_id']}")
    print("STAGE_6B_BUILD_KIT_STATUS=PASS")


if __name__ == "__main__":
    main()
