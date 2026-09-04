"""Deploy Stage 6A Power BI serving views to BigQuery.

Dry-run is the default. ``--execute`` creates only the dedicated Power BI serving views.
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

from pharmstock.analytics.dbt_stage import DBT_PROFILES_RELATIVE, DBT_PROJECT_RELATIVE
from pharmstock.analytics.powerbi_stage import (
    DEFAULT_PBI_DATASET,
    FORBIDDEN_MONETARY_TERMS,
    PBI_TABLE_ALIASES,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deploy Stage 6A Power BI serving layer")
    parser.add_argument("--project", default=os.getenv("PHARMSTOCK_BQ_PROJECT"))
    parser.add_argument(
        "--base-dataset", default=os.getenv("PHARMSTOCK_DBT_BASE_DATASET", "pharmstock")
    )
    parser.add_argument(
        "--pbi-dataset", default=os.getenv("PHARMSTOCK_PBI_DATASET", DEFAULT_PBI_DATASET)
    )
    parser.add_argument("--location", default=os.getenv("PHARMSTOCK_BQ_LOCATION", "EU"))
    parser.add_argument("--execute", action="store_true")
    return parser


def _dbt_executable() -> str | None:
    executable = "dbt.exe" if os.name == "nt" else "dbt"
    beside_python = Path(sys.executable).parent / executable
    if beside_python.is_file():
        return str(beside_python)
    return shutil.which("dbt")


def _env(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    if args.project:
        env["PHARMSTOCK_BQ_PROJECT"] = args.project
    env["PHARMSTOCK_DBT_BASE_DATASET"] = args.base_dataset
    env["PHARMSTOCK_BQ_LOCATION"] = args.location
    env["PHARMSTOCK_PBI_DATASET"] = args.pbi_dataset
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


def _validate_stage5d(args: argparse.Namespace) -> dict[str, object]:
    path = Path("artifacts/stage5d/dimensions_execution_report.json")
    if not path.is_file():
        raise RuntimeError("Stage 6A requires Stage 5D dimensions execution report")
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("cloud_mutation") is not True:
        raise RuntimeError("Stage 5D dimensions report is not a successful cloud execution")
    if report.get("project_id") != args.project:
        raise RuntimeError("Stage 5D project does not match Stage 6A --project")
    if str(report.get("location", "")).upper() != args.location.upper():
        raise RuntimeError("Stage 5D location does not match Stage 6A --location")
    return report


def _verify_views(args: argparse.Namespace) -> dict[str, object]:
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
    client.get_dataset(f"{args.project}.{args.pbi_dataset}")
    gold_dataset = f"{args.base_dataset}_gold"
    mirror_sources = {
        "dim_product": "dim_product",
        "dim_branch": "dim_branch",
        "dim_supplier": "dim_supplier",
        "fact_sales_demand": "fct_daily_sales_demand",
        "fact_inventory_movement": "fct_daily_inventory_movement",
        "fact_reorder_events": "fct_reorder_events",
        "fact_procurement_order_lifecycle": "fct_procurement_order_lifecycle",
        "mart_branch_daily_operations": "mart_branch_daily_operations",
        "mart_product_daily_demand": "mart_product_daily_demand",
        "mart_supplier_procurement_performance": "mart_supplier_procurement_performance",
    }
    verified: list[dict[str, object]] = []
    for alias in PBI_TABLE_ALIASES.values():
        table_id = f"{args.project}.{args.pbi_dataset}.{alias}"
        table = client.get_table(table_id)
        if table.table_type != "VIEW":
            raise RuntimeError(f"{alias} must be a BigQuery VIEW, got {table.table_type}")
        fields = {field.name.lower() for field in table.schema}
        forbidden = sorted(term for term in FORBIDDEN_MONETARY_TERMS if term in fields)
        if forbidden:
            raise RuntimeError(f"forbidden monetary fields in {alias}: {forbidden}")
        query = client.query(f"SELECT COUNT(*) AS n FROM `{table_id}`", location=args.location)
        row_count = int(next(iter(query.result())).n)
        if alias in mirror_sources:
            source = f"{args.project}.{gold_dataset}.{mirror_sources[alias]}"
            source_query = client.query(
                f"SELECT COUNT(*) AS n FROM `{source}`", location=args.location
            )
            source_count = int(next(iter(source_query.result())).n)
            if row_count != source_count:
                raise RuntimeError(f"{alias}: rows {row_count} != gold source {source_count}")
        if alias == "dim_date" and row_count < 1:
            raise RuntimeError("dim_date must contain at least one date")
        verified.append({"table": alias, "table_id": table_id, "row_count": row_count})
        print(f"  verified {alias:<42} rows={row_count:,} type=VIEW")

    return {
        "stage": "6A",
        "executed_at": datetime.now(UTC).isoformat(),
        "cloud_mutation": True,
        "project_id": args.project,
        "adc_project": adc_project,
        "gold_dataset": gold_dataset,
        "powerbi_dataset": args.pbi_dataset,
        "location": args.location,
        "serving_view_count": len(verified),
        "views": verified,
        "recommended_storage_mode": "Import",
        "monetary_measures_generated": False,
        "ready_for_powerbi_desktop": True,
    }


def main() -> None:
    args = _parser().parse_args()
    dbt = _dbt_executable()
    if dbt is None:
        raise SystemExit('dbt executable not found. Install: pip install -e ".[analytics]"')
    expected_pbi_dataset = f"{args.base_dataset}_pbi"
    if args.pbi_dataset != expected_pbi_dataset:
        raise SystemExit(
            f"dbt schema contract requires --pbi-dataset {expected_pbi_dataset!r} "
            f"for base dataset {args.base_dataset!r}"
        )
    env = _env(args)

    print("=== PharmStock V2 / Stage 6A Power BI Serving Deployment ===")
    print(f"Project:          {args.project or 'NOT SET'}")
    print(f"Gold dataset:     {args.base_dataset}_gold")
    print(f"Power BI dataset: {args.pbi_dataset}")
    print(f"Location:         {args.location}")

    if not args.execute:
        _run_dbt(dbt, ["parse", "--no-partial-parse"], env)
        print("Cloud mutation:   NO / DRY RUN")
        print("\nSTAGE_6A_POWERBI_MODE=DRY_RUN")
        return
    if not args.project:
        raise SystemExit("Cloud execution requires --project or PHARMSTOCK_BQ_PROJECT")

    _validate_stage5d(args)
    print("Stage 5D source:  VERIFIED")
    print("Cloud mutation:   YES")
    _run_dbt(dbt, ["debug"], env)
    _run_dbt(dbt, ["build", "--select", "tag:stage6a", "--fail-fast"], env)
    report = _verify_views(args)

    output = Path("artifacts/stage6a")
    output.mkdir(parents=True, exist_ok=True)
    (output / "cloud_execution_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output / "_CLOUD_SUCCESS").write_text(
        "STAGE_6A_CLOUD_STATUS=PASS\n", encoding="utf-8"
    )
    print("\nSTAGE_6A_CLOUD_STATUS=PASS")


if __name__ == "__main__":
    main()
