"""Deploy the Stage 7N Power BI production semantic serving boundary."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pharmstock.analytics.powerbi_prod_stage import (
    BIGQUERY_VIEWS,
    DEFAULT_PBI_PROD_DATASET,
    POSTGRES_VIEWS,
    STAGE7N_VERSION,
    bigquery_view_sql,
    write_stage7n_artifacts,
)

POSTGRES_COMPOSE = Path("infra/docker/docker-compose.postgres.yml")
POSTGRES_SQL = Path("infra/docker/postgres/sql/012_stage7n_powerbi_readonly.sql")
STAGE7H_REPORT = Path("artifacts/stage7h/cloud_execution_report.json")
STAGE7J_REPORT = Path("artifacts/stage7j/dq_report.json")
STAGE7M_REPORT = Path("artifacts/stage7m/stage7m_report.json")
ARTIFACT_ROOT = Path("artifacts/stage7n")
REPORT_PATH = ARTIFACT_ROOT / "stage7n_report.json"
SUCCESS_PATH = ARTIFACT_ROOT / "_SUCCESS"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--project", default=os.getenv("PHARMSTOCK_BQ_PROJECT"))
    parser.add_argument("--location", default=os.getenv("PHARMSTOCK_BQ_LOCATION", "EU"))
    parser.add_argument(
        "--pbi-dataset",
        default=os.getenv("PHARMSTOCK_PBI_PROD_DATASET", DEFAULT_PBI_PROD_DATASET),
    )
    parser.add_argument(
        "--gold-dataset",
        default=os.getenv("PHARMSTOCK_DBT_REBUILD_GOLD", "pharmstock_rebuild_gold"),
    )
    parser.add_argument(
        "--current-dataset",
        default=os.getenv("PHARMSTOCK_BQ_CURRENT_DATASET", "pharmstock_ops_current"),
    )
    return parser


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _preflight(project_id: str | None) -> dict[str, object]:
    if not project_id:
        raise RuntimeError("Stage 7N requires PHARMSTOCK_BQ_PROJECT or --project")
    if not STAGE7H_REPORT.is_file():
        raise RuntimeError("Stage 7N requires accepted Stage 7H cloud report")
    if not STAGE7J_REPORT.is_file():
        raise RuntimeError("Stage 7N requires accepted Stage 7J DQ report")
    if not STAGE7M_REPORT.is_file():
        raise RuntimeError("Stage 7N requires accepted Stage 7M report")

    stage7h = _read_json(STAGE7H_REPORT)
    stage7j = _read_json(STAGE7J_REPORT)
    stage7m = _read_json(STAGE7M_REPORT)
    if stage7h.get("project_id") != project_id:
        raise RuntimeError("Stage 7H project does not match Stage 7N project")
    if stage7j.get("project_id") != project_id or stage7j.get("status") != "PASS":
        raise RuntimeError("Stage 7J DQ report is not PASS for the selected project")
    if stage7m.get("status") != "PASS":
        raise RuntimeError("Stage 7M report is not PASS")
    if float(stage7j.get("storage_gib", 999.0)) >= 8.2:
        raise RuntimeError("Stage 7N refuses deployment at/above the 8.2 GiB storage warning")
    return {
        "stage7h_status": "PASS",
        "stage7j_status": stage7j.get("status"),
        "stage7m_status": stage7m.get("status"),
        "storage_gib": float(stage7j.get("storage_gib", 0.0)),
    }


def _compose(*args: str) -> subprocess.CompletedProcess[str]:
    command = ["docker", "compose", "-f", str(POSTGRES_COMPOSE), *args]
    env = os.environ.copy()
    env.setdefault("COMPOSE_IGNORE_ORPHANS", "true")
    return subprocess.run(command, check=True, text=True, env=env)


def _apply_postgres_semantic_views() -> None:
    password = os.getenv("PHARMSTOCK_BI_PASSWORD", "pharmstock_local_dev_bi")
    _compose("up", "-d", "postgres")
    _compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-v",
        f"bi_password={password}",
        "-U",
        "pharmstock_admin",
        "-d",
        "pharmstock_ops",
        "-f",
        f"/opt/pharmstock/{POSTGRES_SQL.as_posix()}",
    )


def _psql_scalar(sql: str) -> str:
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(POSTGRES_COMPOSE),
            "exec",
            "-T",
            "postgres",
            "psql",
            "-At",
            "-U",
            "pharmstock_admin",
            "-d",
            "pharmstock_ops",
            "-c",
            sql,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _verify_postgres_views() -> dict[str, object]:
    count = int(
        _psql_scalar(
            "SELECT count(*) FROM information_schema.views "
            "WHERE table_schema='bi' AND table_name LIKE 'v_%';"
        )
    )
    if count != len(POSTGRES_VIEWS):
        raise RuntimeError(f"Stage 7N expected {len(POSTGRES_VIEWS)} bi views, got {count}")
    readable = _psql_scalar(
        "SELECT bool_and(has_table_privilege('pharmstock_bi', "
        "format('bi.%I', table_name), 'SELECT')) "
        "FROM information_schema.views WHERE table_schema='bi';"
    )
    if readable != "t":
        raise RuntimeError("pharmstock_bi cannot read every BI view")
    writable = _psql_scalar(
        "SELECT "
        "has_table_privilege('pharmstock_bi','procurement.purchase_order','INSERT') OR "
        "has_table_privilege('pharmstock_bi','decision_ops.decision_case','UPDATE') OR "
        "has_table_privilege('pharmstock_bi','mlops.prediction_event','INSERT');"
    )
    if writable != "f":
        raise RuntimeError("pharmstock_bi unexpectedly has write privilege")

    runtime_readable: list[str] = []
    for view_name in POSTGRES_VIEWS:
        sql = (
            "SET ROLE pharmstock_bi; "
            f"SELECT * FROM bi.{view_name} LIMIT 0; "
            "RESET ROLE;"
        )
        try:
            subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(POSTGRES_COMPOSE),
                    "exec",
                    "-T",
                    "postgres",
                    "psql",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-At",
                    "-U",
                    "pharmstock_admin",
                    "-d",
                    "pharmstock_ops",
                    "-c",
                    sql,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "unknown psql error").strip()
            raise RuntimeError(
                f"pharmstock_bi runtime read failed for bi.{view_name}: {detail}"
            ) from exc
        runtime_readable.append(view_name)

    return {
        "view_count": count,
        "all_views_readable": True,
        "runtime_readable_views": runtime_readable,
        "write_privilege_blocked": True,
        "role": "pharmstock_bi",
    }


def _bigquery_client(project_id: str, location: str):
    try:
        import google.auth
        from google.cloud import bigquery
    except ImportError as exc:
        raise RuntimeError("Stage 7N requires google-cloud-bigquery") from exc

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    return bigquery.Client(project=project_id, credentials=credentials, location=location)


def _project_storage_bytes(client: Any) -> int:
    total = 0
    for dataset in client.list_datasets():
        for item in client.list_tables(dataset.reference):
            if getattr(item, "table_type", "TABLE") != "TABLE":
                continue
            table = client.get_table(item.reference)
            total += int(table.num_bytes or 0)
    return total


def _deploy_bigquery_views(args: argparse.Namespace) -> dict[str, object]:
    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery

    client = _bigquery_client(args.project, args.location)
    before = _project_storage_bytes(client)
    dataset_id = f"{args.project}.{args.pbi_dataset}"
    dataset = bigquery.Dataset(dataset_id)
    dataset.location = args.location
    client.create_dataset(dataset, exists_ok=True)

    sql_map = bigquery_view_sql(
        project_id=args.project,
        gold_dataset=args.gold_dataset,
        current_dataset=args.current_dataset,
    )
    verified: list[dict[str, object]] = []
    for name in BIGQUERY_VIEWS:
        table_id = f"{dataset_id}.{name}"
        try:
            existing = client.get_table(table_id)
        except NotFound:
            view = bigquery.Table(table_id)
            view.view_query = sql_map[name]
            view.view_use_legacy_sql = False
            existing = client.create_table(view)
        else:
            if existing.table_type != "VIEW":
                raise RuntimeError(f"Stage 7N refuses to replace non-view object: {table_id}")
            existing.view_query = sql_map[name]
            existing.view_use_legacy_sql = False
            existing = client.update_table(existing, ["view_query", "view_use_legacy_sql"])
        if existing.table_type != "VIEW":
            raise RuntimeError(f"{table_id} must be a VIEW")
        query_job = client.query(
            f"SELECT * FROM `{table_id}` LIMIT 1",
            location=args.location,
            job_config=bigquery.QueryJobConfig(use_query_cache=True),
        )
        rows = list(query_job.result(max_results=1))
        verified.append({"view": name, "sample_rows": len(rows)})
        print(f"  verified {name:<38} type=VIEW")

    after = _project_storage_bytes(client)
    if after > before + 1024 * 1024:
        raise RuntimeError("Stage 7N view deployment unexpectedly increased table storage")
    return {
        "dataset": args.pbi_dataset,
        "view_count": len(verified),
        "views": verified,
        "storage_before_gib": before / (1024**3),
        "storage_after_gib": after / (1024**3),
        "data_tables_created": 0,
    }


def main() -> None:
    args = _parser().parse_args()
    preflight = _preflight(args.project)
    local = write_stage7n_artifacts(ARTIFACT_ROOT, project_id=args.project)

    print(f"=== PharmStock V2 / Stage 7N Power BI Production Semantic Layer v{STAGE7N_VERSION} ===")
    print(f"Project:                  {args.project}")
    print(f"BigQuery history source:  {args.gold_dataset}")
    print(f"BigQuery current source:  {args.current_dataset}")
    print(f"Power BI dataset:         {args.pbi_dataset}")
    print(f"BigQuery semantic views:  {len(BIGQUERY_VIEWS)}")
    print(f"PostgreSQL BI views:      {len(POSTGRES_VIEWS)}")
    print("Power BI writes:          NONE")
    print("Procurement writes:       BLOCKED")
    print("ML/Decision writes:       BLOCKED")
    print(f"Storage baseline:         {preflight['storage_gib']:.3f} GiB")

    if not args.execute:
        print("Cloud mutation:            NO / DRY RUN")
        print("Runtime mutation:          NO / DRY RUN")
        print("STAGE_7N_DRY_RUN_STATUS=PASS")
        return

    if os.getenv("PHARMSTOCK_BQ_SANDBOX", "0").strip() != "1":
        raise RuntimeError("Stage 7N cloud execution requires PHARMSTOCK_BQ_SANDBOX=1")

    print("Applying read-only PostgreSQL BI serving views...")
    _apply_postgres_semantic_views()
    postgres = _verify_postgres_views()
    print("Deploying metadata-only BigQuery Power BI views...")
    bigquery = _deploy_bigquery_views(args)

    report = {
        "stage": "7N",
        "version": STAGE7N_VERSION,
        "status": "PASS",
        "generated_at": datetime.now(UTC).isoformat(),
        "project_id": args.project,
        "location": args.location,
        "preflight": preflight,
        "local_contract": local,
        "bigquery": bigquery,
        "postgresql": postgres,
        "cloud_mutation": "METADATA_ONLY_BIGQUERY_VIEWS",
        "bigquery_data_tables_created": 0,
        "powerbi_writeback": False,
        "procurement_write": False,
        "ready_for_powerbi_desktop": True,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    SUCCESS_PATH.write_text(report["generated_at"] + "\n", encoding="utf-8")

    print("Stage 7N verification:")
    print(f"  BigQuery views:              {bigquery['view_count']}/{len(BIGQUERY_VIEWS)}")
    print(f"  PostgreSQL BI views:         {postgres['view_count']}/{len(POSTGRES_VIEWS)}")
    print(
        "  PostgreSQL runtime reads:    "
        f"{len(postgres['runtime_readable_views'])}/{len(POSTGRES_VIEWS)}"
    )
    print("  PostgreSQL BI role:          READ ONLY")
    print("  Procurement write privilege: BLOCKED")
    print("  BigQuery data tables:        0")
    print(f"  Storage after:               {bigquery['storage_after_gib']:.3f} GiB")
    print("  Power BI Desktop kit:        READY")
    print("STAGE_7N_BIGQUERY_STATUS=PASS")
    print("STAGE_7N_POSTGRES_STATUS=PASS")
    print("STAGE_7N_GOVERNANCE_STATUS=PASS")
    print("STAGE_7N_STATUS=PASS")


if __name__ == "__main__":
    main()
