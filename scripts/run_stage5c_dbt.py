"""Explicit Stage 5C dbt BigQuery execution.

Default mode is local-only ``dbt parse``. Cloud mutation requires ``--execute``.
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
    DEFAULT_SOURCE_DATASET,
    FORBIDDEN_MONETARY_TOKENS,
    GOLD_MODELS,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Stage 5C dbt analytics on BigQuery")
    parser.add_argument("--project", default=os.getenv("PHARMSTOCK_BQ_PROJECT"))
    parser.add_argument(
        "--source-dataset",
        default=os.getenv("PHARMSTOCK_BQ_SOURCE_DATASET", DEFAULT_SOURCE_DATASET),
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


def _dbt_environment(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    if args.project:
        env["PHARMSTOCK_BQ_PROJECT"] = args.project
    env["PHARMSTOCK_BQ_SOURCE_DATASET"] = args.source_dataset
    env["PHARMSTOCK_DBT_BASE_DATASET"] = args.base_dataset
    env["PHARMSTOCK_BQ_LOCATION"] = args.location
    return env


def _run_dbt(dbt: str, command: list[str], env: dict[str, str]) -> None:
    full_command = [
        dbt,
        *command,
        "--project-dir",
        str(DBT_PROJECT_RELATIVE),
        "--profiles-dir",
        str(DBT_PROFILES_RELATIVE),
    ]
    result = subprocess.run(full_command, env=env, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def _validate_stage5b_report(args: argparse.Namespace) -> dict[str, object]:
    path = Path("artifacts/stage5b/cloud_execution_report.json")
    if not path.is_file():
        raise RuntimeError("Stage 5C execution requires Stage 5B cloud execution report")
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("cloud_mutation") is not True:
        raise RuntimeError("Stage 5B report is not a successful cloud execution")
    if report.get("project_id") != args.project:
        raise RuntimeError("Stage 5B project does not match Stage 5C --project")
    if report.get("dataset_id") != args.source_dataset:
        raise RuntimeError("Stage 5B dataset does not match Stage 5C --source-dataset")
    if str(report.get("location", "")).upper() != args.location.upper():
        raise RuntimeError("Stage 5B location does not match Stage 5C --location")
    return report


def _verify_gold(args: argparse.Namespace) -> dict[str, object]:
    try:
        import google.auth
        from google.cloud import bigquery
    except ImportError as exc:
        raise RuntimeError('Install cloud dependencies: pip install -e ".[gcp,analytics]"') from exc

    credentials, adc_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    client = bigquery.Client(
        project=args.project,
        credentials=credentials,
        location=args.location,
    )
    gold_dataset = f"{args.base_dataset}_gold"
    staging_dataset = f"{args.base_dataset}_stg"
    client.get_dataset(f"{args.project}.{gold_dataset}")
    client.get_dataset(f"{args.project}.{staging_dataset}")

    tables: list[dict[str, object]] = []
    for model in GOLD_MODELS:
        table_id = f"{args.project}.{gold_dataset}.{model}"
        table = client.get_table(table_id)
        field_names = {field.name.lower() for field in table.schema}
        forbidden = sorted(
            token for token in FORBIDDEN_MONETARY_TOKENS if token.lower() in field_names
        )
        if forbidden:
            raise RuntimeError(f"forbidden monetary fields in {model}: {forbidden}")
        query = client.query(
            f"SELECT COUNT(*) AS row_count FROM `{table_id}`",
            location=args.location,
        )
        first = next(iter(query.result()))
        row_count = int(first.row_count)
        tables.append({"model": model, "table_id": table_id, "row_count": row_count})
        print(f"  verified {model:<42} rows={row_count:,}")

    return {
        "stage": "5C",
        "executed_at": datetime.now(UTC).isoformat(),
        "cloud_mutation": True,
        "project_id": args.project,
        "adc_project": adc_project,
        "source_dataset": args.source_dataset,
        "staging_dataset": staging_dataset,
        "gold_dataset": gold_dataset,
        "location": args.location,
        "gold_model_count": len(tables),
        "gold_tables": tables,
        "monetary_measures_generated": False,
    }


def main() -> None:
    args = _parser().parse_args()
    dbt = _dbt_executable()
    if dbt is None:
        raise SystemExit('dbt executable not found. Install: pip install -e ".[analytics]"')

    env = _dbt_environment(args)
    print("=== PharmStock V2 / Stage 5C dbt Analytics Deployment ===")
    print(f"Project:          {args.project or 'NOT SET'}")
    print(f"Source dataset:   {args.source_dataset}")
    print(f"Staging dataset:  {args.base_dataset}_stg")
    print(f"Gold dataset:     {args.base_dataset}_gold")
    print(f"Location:         {args.location}")

    if not args.execute:
        _run_dbt(dbt, ["parse", "--no-partial-parse"], env)
        print("Cloud mutation:   NO / DRY RUN")
        print("\nSTAGE_5C_DBT_MODE=DRY_RUN")
        return

    if not args.project:
        raise SystemExit("Cloud execution requires --project or PHARMSTOCK_BQ_PROJECT")
    _validate_stage5b_report(args)
    print("Stage 5B source:  VERIFIED")
    print("Cloud mutation:   YES")

    _run_dbt(dbt, ["debug"], env)
    _run_dbt(dbt, ["build", "--fail-fast"], env)
    _run_dbt(dbt, ["docs", "generate"], env)
    report = _verify_gold(args)

    output = Path("artifacts/stage5c")
    output.mkdir(parents=True, exist_ok=True)
    (output / "cloud_execution_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output / "_CLOUD_SUCCESS").write_text(
        "STAGE_5C_CLOUD_STATUS=PASS\n", encoding="utf-8"
    )
    print("\nSTAGE_5C_CLOUD_STATUS=PASS")


if __name__ == "__main__":
    main()
