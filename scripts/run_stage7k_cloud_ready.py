"""Validate and optionally persist the zero-cost Stage 7K.4 cloud blueprint."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from pharmstock.ml.cloud_ready import cloud_ready_plan

ROOT = Path("artifacts/stage7k/cloud_ready")
TERRAFORM_DIR = Path("infra/terraform/stage7k_cloud_ready")
REQUIRED_FILES = {
    "versions.tf",
    "variables.tf",
    "main.tf",
    "outputs.tf",
    "terraform.tfvars.example",
    "README.md",
}


def _validate_terraform_blueprint() -> None:
    missing = sorted(name for name in REQUIRED_FILES if not (TERRAFORM_DIR / name).is_file())
    if missing:
        raise RuntimeError(f"cloud-ready Terraform blueprint is incomplete: {missing}")
    variables = (TERRAFORM_DIR / "variables.tf").read_text(encoding="utf-8")
    main = (TERRAFORM_DIR / "main.tf").read_text(encoding="utf-8")
    if 'default     = false' not in variables:
        raise RuntimeError("billable-resource Terraform guard must default to false")
    if "var.enable_billable_resources ? 1 : 0" not in main:
        raise RuntimeError("billable Terraform resources are missing the explicit guard")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 7K.4 zero-cost cloud readiness")
    parser.add_argument("--write-plan", action="store_true", help="write local JSON plan only")
    args = parser.parse_args()
    project_id = os.getenv("PHARMSTOCK_BQ_PROJECT", "pharmstock-ai-bq2-2026").strip()
    region = os.getenv("PHARMSTOCK_CLOUD_REGION", "europe-west1").strip()
    _validate_terraform_blueprint()
    plan = cloud_ready_plan(project_id, region)
    plan["generated_at"] = datetime.now(UTC).isoformat()

    print("=== PharmStock Stage 7K.4 / Cloud-Ready Blueprint ===")
    print(f"Project:                 {project_id}")
    print(f"Region blueprint:        {region}")
    print("Cloud API calls:         NONE")
    print("Terraform apply:         DISABLED")
    print("Artifact push:           NONE")
    print("Vertex deployment:       NONE")
    print("Cloud Run deployment:    NONE")
    print("Billing change:          NONE")
    print("Paid resources created:  NONE")
    if args.write_plan:
        ROOT.mkdir(parents=True, exist_ok=True)
        (ROOT / "cloud_ready_plan.json").write_text(
            json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(f"Local plan:              {ROOT / 'cloud_ready_plan.json'}")
    print("STAGE_7K4_CLOUD_READY_BLUEPRINT_STATUS=PASS")
    print("STAGE_7K4_CLOUD_MUTATION=NO")


if __name__ == "__main__":
    main()
