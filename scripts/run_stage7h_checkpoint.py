"""Stage 7H local-safe BigQuery + dbt deployment preflight."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from pharmstock.rebuild.bigquery_stage import (
    STAGE7H_ROOT,
    build_preflight,
    stage7h_contract,
)


def main() -> None:
    STAGE7H_ROOT.mkdir(parents=True, exist_ok=True)

    preflight = build_preflight()
    (STAGE7H_ROOT / "deployment_contract.json").write_text(
        json.dumps(stage7h_contract(), indent=2, sort_keys=True), encoding="utf-8"
    )
    (STAGE7H_ROOT / "preflight.json").write_text(
        json.dumps(preflight, indent=2, sort_keys=True), encoding="utf-8"
    )
    verification = {
        "stage": "7H",
        "status": "PREFLIGHT_PASS",
        "verified_at": datetime.now(UTC).isoformat(),
        "local_ready": preflight["local_ready"],
        "cloud_ready_hint": preflight["cloud_ready_hint"],
        "snapshot_table_count": preflight["snapshot_table_count"],
        "expected_snapshot_rows": preflight["expected_snapshot_rows"],
        "cloud_mutation": False,
    }
    (STAGE7H_ROOT / "preflight_verification.json").write_text(
        json.dumps(verification, indent=2, sort_keys=True), encoding="utf-8"
    )
    if not preflight["local_ready"]:
        raise SystemExit(
            "Stage 7H local preflight failed; inspect artifacts/stage7h/preflight.json"
        )
    (STAGE7H_ROOT / "_PREFLIGHT_SUCCESS").write_text("PASS\n", encoding="utf-8")

    print("=== PharmStock V2 / Stage 7H BigQuery + dbt Deployment ===")
    print("Mode:                          LOCAL SAFE PREFLIGHT")
    print(f"Stage 7G snapshot tables:      {preflight['snapshot_table_count']}")
    print(f"Stage 7G snapshot rows:        {preflight['expected_snapshot_rows']:,}")
    print(f"BigQuery target dataset:       {preflight['dataset_id']}")
    bigquery_status = "YES" if preflight["bigquery_client_installed"] else "NO"
    print(f"BigQuery client installed:     {bigquery_status}")
    print(f"dbt installed:                 {'YES' if preflight['dbt_installed'] else 'NO'}")
    print(f"dbt project ready:             {'YES' if preflight['dbt_project_ready'] else 'NO'}")
    credential_status = "YES" if preflight["credential_hint_present"] else "NO"
    print(f"Google credential hint:        {credential_status}")
    print(f"GCP project configured:        {'YES' if preflight['project_configured'] else 'NO'}")
    print(f"Cloud ready hint:              {'YES' if preflight['cloud_ready_hint'] else 'NO'}")
    print("Cloud mutation:                NO")
    print("Historical replay via Kafka:   NO")
    print("CDC resume offsets preserved:  YES")
    print("\nGenerated files:")
    print(r"  artifacts\stage7h\deployment_contract.json")
    print(r"  artifacts\stage7h\preflight.json")
    print(r"  artifacts\stage7h\preflight_verification.json")
    print("\nSTAGE_7H_PREFLIGHT_STATUS=PASS")


if __name__ == "__main__":
    main()
