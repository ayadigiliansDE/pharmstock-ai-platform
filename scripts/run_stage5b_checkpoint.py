"""Stage 5B local-safe BigQuery cloud integration readiness checkpoint."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from pharmstock.warehouse.bigquery_cloud import (
    cloud_config_from_environment,
    write_stage5b_local_plan,
)


def main() -> None:
    stage5a = Path("artifacts/stage5a")
    stage5b = Path("artifacts/stage5b")
    if not (stage5a / "_SUCCESS").exists():
        raise RuntimeError("Stage 5B requires a completed Stage 5A checkpoint")
    if stage5b.exists():
        shutil.rmtree(stage5b)

    config = cloud_config_from_environment()
    plan = write_stage5b_local_plan(stage5b, stage5a, config)
    readiness = plan["readiness"]
    if not readiness["local_ready"]:
        raise RuntimeError("Stage 5B local warehouse preflight failed")

    verification = {
        "stage": "5B",
        "verified_at": datetime.now(UTC).isoformat(),
        "local_ready": True,
        "cloud_preconditions_present": readiness["cloud_preconditions_present"],
        "cloud_mutation_performed": False,
        "table_count": len(plan["tables"]),
        "expected_physical_rows": sum(
            int(table["expected_rows"]) for table in plan["tables"]
        ),
        "project_id": plan["project_id"],
        "dataset_id": plan["dataset_id"],
        "location": plan["location"],
    }
    (stage5b / "local_verification.json").write_text(
        json.dumps(verification, indent=2, sort_keys=True), encoding="utf-8"
    )
    (stage5b / "_SUCCESS").write_text("STAGE_5B_LOCAL_READY\n", encoding="utf-8")

    print("=== PharmStock V2 / Stage 5B BigQuery Cloud Integration ===")
    print("Mode:                     LOCAL SAFE PREFLIGHT")
    print("Stage 5A warehouse:       VERIFIED")
    print(f"BigQuery tables:          {verification['table_count']}")
    print(f"Expected physical rows:   {verification['expected_physical_rows']:,}")
    print(f"Project configured:       {'YES' if readiness['project_configured'] else 'NO'}")
    print(f"BigQuery client installed:{'YES' if readiness['client_installed'] else 'NO'}")
    credential_hint = "YES" if readiness["credential_hint_present"] else "NO"
    preconditions = "YES" if readiness["cloud_preconditions_present"] else "NO"
    print(f"ADC credential hint:      {credential_hint}")
    print(f"Cloud preconditions:      {preconditions}")
    print("Cloud mutation performed: NO")
    print("\nGenerated files:")
    print(f"  {(stage5b / 'cloud_readiness.json').resolve()}")
    print(f"  {(stage5b / 'deployment_plan.json').resolve()}")
    print(f"  {(stage5b / 'local_verification.json').resolve()}")
    print("\nSTAGE_5B_STATUS=PASS")


if __name__ == "__main__":
    main()
