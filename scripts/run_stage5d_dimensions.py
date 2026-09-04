"""Build Stage 5D master dimensions with dbt.

Dry-run is the default. ``--execute`` performs a BigQuery dbt build and verifies dimensions.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from pharmstock.analytics.dbt_stage import (
    DBT_PROFILES_RELATIVE,
    DBT_PROJECT_RELATIVE,
    DEFAULT_DBT_BASE_DATASET,
    DEFAULT_LOCATION,
)
from pharmstock.analytics.dimensions_stage import DIMENSION_MODELS
from pharmstock.masterdata.stage5d import DEFAULT_MASTER_DATASET


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Stage 5D dbt master dimensions")
    parser.add_argument("--project", default=os.getenv("PHARMSTOCK_BQ_PROJECT"))
    parser.add_argument(
        "--master-dataset",
        default=os.getenv("PHARMSTOCK_BQ_MASTER_DATASET", DEFAULT_MASTER_DATASET),
    )
    parser.add_argument(
        "--base-dataset",
        default=os.getenv("PHARMSTOCK_DBT_BASE_DATASET", DEFAULT_DBT_BASE_DATASET),
    )
    parser.add_argument(
        "--location", default=os.getenv("PHARMSTOCK_BQ_LOCATION", DEFAULT_LOCATION)
    )
    parser.add_argument("--execute", action="store_true")
    return parser


def _dbt_executable() -> str | None:
    executable = "dbt.exe" if os.name == "nt" else "dbt"
    beside_python = Path(sys.executable).parent / executable
    if beside_python.is_file():
        return str(beside_python)
    return shutil.which("dbt")


def _environment(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    if args.project:
        env["PHARMSTOCK_BQ_PROJECT"] = args.project
    env["PHARMSTOCK_BQ_MASTER_DATASET"] = args.master_dataset
    env["PHARMSTOCK_DBT_BASE_DATASET"] = args.base_dataset
    env["PHARMSTOCK_BQ_LOCATION"] = args.location
    return env


def _run_dbt(dbt: str, command: list[str], env: dict[str, str]) -> None:
    full = [
        dbt,
        *command,
        "--project-dir",
        str(DBT_PROJECT_RELATIVE),
        "--profiles-dir",
        str(DBT_PROFILES_RELATIVE),
    ]
    result = subprocess.run(full, env=env, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def _validate_cloud_source(args: argparse.Namespace) -> dict[str, object]:
    path = Path("artifacts/stage5d/cloud_execution_report.json")
    if not path.is_file():
        raise RuntimeError("Stage 5D dimensions require the master cloud execution report")
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("cloud_mutation") is not True:
        raise RuntimeError("Stage 5D master cloud execution was not successful")
    if report.get("project_id") != args.project:
        raise RuntimeError("Stage 5D master project does not match --project")
    if report.get("dataset_id") != args.master_dataset:
        raise RuntimeError("Stage 5D master dataset does not match --master-dataset")
    if str(report.get("location", "")).upper() != args.location.upper():
        raise RuntimeError("Stage 5D master location does not match --location")
    return report


def _verify_dimensions(
    args: argparse.Namespace, master_report: dict[str, object]
) -> dict[str, object]:
    try:
        import google.auth
        from google.cloud import bigquery
    except ImportError as exc:
        raise RuntimeError('Install dependencies: pip install -e ".[gcp,analytics]"') from exc

    credentials, adc_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    client = bigquery.Client(
        project=args.project,
        credentials=credentials,
        location=args.location,
    )
    gold_dataset = f"{args.base_dataset}_gold"
    expected_map = {
        "dim_product": int(next(
            item["row_count"] for item in master_report["tables"]
            if item["table"] == "product_master"
        )),
        "dim_branch": int(next(
            item["row_count"] for item in master_report["tables"]
            if item["table"] == "pharmacy_branch_master"
        )),
        "dim_supplier": int(next(
            item["row_count"] for item in master_report["tables"]
            if item["table"] == "supplier_master"
        )),
    }
    verified: list[dict[str, object]] = []
    for model in DIMENSION_MODELS:
        table_id = f"{args.project}.{gold_dataset}.{model}"
        table = client.get_table(table_id)
        expected = expected_map[model]
        if int(table.num_rows) != expected:
            raise RuntimeError(
                f"{model}: dimension rows {table.num_rows} != expected master rows {expected}"
            )
        verified.append({"model": model, "table_id": table_id, "row_count": expected})
        print(f"  verified {model:<20} rows={expected:,}")
    return {
        "stage": "5D",
        "executed_at": datetime.now(UTC).isoformat(),
        "cloud_mutation": True,
        "project_id": args.project,
        "adc_project": adc_project,
        "master_dataset": args.master_dataset,
        "gold_dataset": gold_dataset,
        "location": args.location,
        "dimension_model_count": len(verified),
        "dimensions": verified,
        "power_bi_dimension_ready": True,
        "monetary_measures_generated": False,
    }


def main() -> None:
    args = _parser().parse_args()
    dbt = _dbt_executable()
    if dbt is None:
        raise SystemExit('dbt executable not found. Install: pip install -e ".[analytics]"')
    env = _environment(args)
    print("=== PharmStock V2 / Stage 5D dbt Master Dimensions ===")
    print(f"Project:          {args.project or 'NOT SET'}")
    print(f"Master dataset:   {args.master_dataset}")
    print(f"Gold dataset:     {args.base_dataset}_gold")
    print(f"Location:         {args.location}")

    if not args.execute:
        _run_dbt(dbt, ["parse", "--no-partial-parse"], env)
        print("Cloud mutation:   NO / DRY RUN")
        print("\nSTAGE_5D_DIMENSIONS_MODE=DRY_RUN")
        return
    if not args.project:
        raise SystemExit("Cloud execution requires --project or PHARMSTOCK_BQ_PROJECT")

    master_report = _validate_cloud_source(args)
    print("Master source:    VERIFIED")
    print("Cloud mutation:   YES")
    _run_dbt(dbt, ["debug"], env)
    _run_dbt(dbt, ["build", "--fail-fast"], env)
    _run_dbt(dbt, ["docs", "generate"], env)
    report = _verify_dimensions(args, master_report)
    output = Path("artifacts/stage5d")
    (output / "dimensions_execution_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output / "_DIMENSIONS_SUCCESS").write_text(
        "STAGE_5D_DIMENSIONS_STATUS=PASS\n", encoding="utf-8"
    )
    print("\nSTAGE_5D_DIMENSIONS_STATUS=PASS")


if __name__ == "__main__":
    main()
