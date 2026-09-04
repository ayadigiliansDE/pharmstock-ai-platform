"""Deploy and verify the Stage 7D local on-prem PostgreSQL operational database."""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import time
from pathlib import Path

from pharmstock.onprem import (
    CDC_TABLES,
    POSTGRES_DATABASE,
    POSTGRES_IMAGE,
    assert_stage_success,
    database_contract,
    input_row_counts,
    write_database_contract,
)

COMPOSE_FILE = Path("infra/docker/docker-compose.postgres.yml")
SCHEMA_SQL = "/opt/pharmstock/infra/docker/postgres/sql/001_schema.sql"
ROLES_CDC_SQL = "/opt/pharmstock/infra/docker/postgres/sql/002_roles_and_cdc.sql"
LOAD_SQL = "/opt/pharmstock/infra/docker/postgres/sql/003_load_stage7d.sql"
VERIFY_SQL = "/opt/pharmstock/infra/docker/postgres/sql/004_verify_stage7d.sql"
OUTPUT_DIR = Path("artifacts/stage7d")


class Stage7DExecutionError(RuntimeError):
    """Raised when Docker or PostgreSQL cannot satisfy the Stage 7D checkpoint."""


def _run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=capture,
    )


def _compose(*args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return _run(["docker", "compose", "-f", str(COMPOSE_FILE), *args], capture=capture)


def _psql_file(path: str, *, variables: bool = False) -> None:
    if variables:
        shell = (
            'PGPASSWORD="$POSTGRES_PASSWORD" psql -v ON_ERROR_STOP=1 '
            '-U "$POSTGRES_USER" -d "$POSTGRES_DB" '
            '-v app_password="$PHARMSTOCK_APP_PASSWORD" '
            '-v cdc_password="$PHARMSTOCK_CDC_PASSWORD" '
            f'-f "{path}"'
        )
    else:
        shell = (
            'PGPASSWORD="$POSTGRES_PASSWORD" psql -v ON_ERROR_STOP=1 '
            '-U "$POSTGRES_USER" -d "$POSTGRES_DB" '
            f'-f "{path}"'
        )
    _compose("exec", "-T", "postgres", "bash", "-lc", shell)


def _verify_output() -> dict[str, str]:
    shell = (
        'PGPASSWORD="$POSTGRES_PASSWORD" psql -v ON_ERROR_STOP=1 '
        '-U "$POSTGRES_USER" -d "$POSTGRES_DB" '
        f'-f "{VERIFY_SQL}"'
    )
    result = _compose(
        "exec",
        "-T",
        "postgres",
        "bash",
        "-lc",
        shell,
        capture=True,
    )
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        text = line.strip()
        if "=" not in text:
            continue
        key, value = text.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _wait_for_postgres(timeout_seconds: float = 90.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = _compose("ps", "--status", "running", "--services", capture=True)
        if "postgres" in result.stdout.split():
            try:
                health = _compose(
                    "exec",
                    "-T",
                    "postgres",
                    "pg_isready",
                    "-U",
                    "pharmstock_admin",
                    "-d",
                    POSTGRES_DATABASE,
                    capture=True,
                )
                if "accepting connections" in health.stdout:
                    return
            except subprocess.CalledProcessError:
                pass
        time.sleep(2)
    raise Stage7DExecutionError("PostgreSQL did not become ready within 90 seconds")


def _expected_terminals(branch_csv: Path) -> int:
    total = 0
    with branch_csv.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            total += int(row["checkout_points"])
    return total


def _integer(values: dict[str, str], key: str) -> int:
    try:
        return int(values[key])
    except (KeyError, ValueError) as exc:
        raise Stage7DExecutionError(f"invalid PostgreSQL verification value: {key}") from exc


def _validate(
    values: dict[str, str],
    expected: dict[str, int],
    expected_terminals: int,
) -> dict[str, object]:
    checks = {
        "postgres_18": values.get("postgres_version", "").startswith("18."),
        "wal_level_logical": values.get("wal_level") == "logical",
        "replication_slots_ready": _integer(values, "max_replication_slots") >= 10,
        "wal_senders_ready": _integer(values, "max_wal_senders") >= 10,
        "scram_passwords": values.get("password_encryption") == "scram-sha-256",
        "product_rows_match": _integer(values, "product") == expected["master.product"],
        "price_rows_match": (
            _integer(values, "price_history") == expected["master.product_price_history"]
        ),
        "organization_rows_match": (
            _integer(values, "organization") == expected["master.pharmacy_organization"]
        ),
        "branch_rows_match": _integer(values, "branch") == expected["master.pharmacy_branch"],
        "all_27_governorates": _integer(values, "governorates") == 27,
        "economics_rows_match": (
            _integer(values, "product_economics")
            == expected["commercial.product_unit_economics"]
        ),
        "branch_policy_rows_match": (
            _integer(values, "branch_policy")
            == expected["commercial.branch_commercial_policy"]
        ),
        "terminal_rows_match_checkout_points": _integer(values, "terminal") == expected_terminals,
        "cdc_role_ready": _integer(values, "cdc_role") == 1,
        "app_role_ready": _integer(values, "app_role") == 1,
        "cdc_publication_ready": _integer(values, "publication") == 1,
        "cdc_publication_tables": _integer(values, "publication_tables") == len(CDC_TABLES),
        "product_finance_fk": _integer(values, "product_finance_orphans") == 0,
        "branch_policy_fk": _integer(values, "branch_policy_orphans") == 0,
        "branch_organization_fk": _integer(values, "branch_org_orphans") == 0,
        "price_product_fk": _integer(values, "price_product_orphans") == 0,
        "retail_price_reconciles": _integer(values, "economics_price_mismatch") == 0,
    }
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise Stage7DExecutionError("Stage 7D database checks failed: " + ", ".join(failed))
    return {
        "status": "PASS",
        "checks": checks,
        "postgres": {
            "version": values["postgres_version"],
            "wal_level": values["wal_level"],
            "max_replication_slots": _integer(values, "max_replication_slots"),
            "max_wal_senders": _integer(values, "max_wal_senders"),
            "password_encryption": values["password_encryption"],
        },
        "row_counts": {
            "product": _integer(values, "product"),
            "product_price_history": _integer(values, "price_history"),
            "pharmacy_organization": _integer(values, "organization"),
            "pharmacy_branch": _integer(values, "branch"),
            "product_unit_economics": _integer(values, "product_economics"),
            "branch_commercial_policy": _integer(values, "branch_policy"),
            "pos_terminal": _integer(values, "terminal"),
            "existing_sale_header": _integer(values, "sale_header"),
            "existing_sale_line": _integer(values, "sale_line"),
        },
        "cdc": {
            "publication_tables": _integer(values, "publication_tables"),
            "replication_role_ready": True,
            "replication_slot_created": False,
            "connector_deployed": False,
        },
        "local_database_mutation_performed": True,
        "cloud_mutation_performed": False,
    }


def _write_outputs(report: dict[str, object], expected: dict[str, int]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_database_contract(OUTPUT_DIR / "database_contract.json")
    (OUTPUT_DIR / "load_verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    cdc = database_contract()["cdc"]
    (OUTPUT_DIR / "cdc_readiness.json").write_text(
        json.dumps(cdc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT_DIR / "input_row_counts.json").write_text(
        json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT_DIR / "_SUCCESS").write_text("STAGE_7D_STATUS=PASS\n", encoding="utf-8")


def main() -> None:
    if shutil.which("docker") is None:
        raise SystemExit("Docker CLI is required for Stage 7D")
    if not COMPOSE_FILE.is_file():
        raise SystemExit(f"missing compose file: {COMPOSE_FILE}")

    assert_stage_success()
    expected = input_row_counts()
    expected_terminals = _expected_terminals(
        Path("artifacts/stage7b/production_pharmacy_branches.csv")
    )

    print("=== PharmStock V2 / Stage 7D On-Prem PostgreSQL Operational Database ===")
    print(f"PostgreSQL image:            {POSTGRES_IMAGE}")
    print(f"Database:                    {POSTGRES_DATABASE}")
    print("Host endpoint:               localhost:5433")
    print("CDC target:                  Debezium / pgoutput (next stage)")
    print("Starting PostgreSQL...", flush=True)

    try:
        _compose("up", "-d", "postgres")
        _wait_for_postgres()
        _psql_file(SCHEMA_SQL)
        _psql_file(ROLES_CDC_SQL, variables=True)
        _psql_file(LOAD_SQL)
        values = _verify_output()
        report = _validate(values, expected, expected_terminals)
    except subprocess.CalledProcessError as exc:
        message = f"Stage 7D Docker/PostgreSQL command failed with code {exc.returncode}"
        raise SystemExit(message) from exc
    except Stage7DExecutionError as exc:
        raise SystemExit(str(exc)) from exc

    _write_outputs(report, expected)
    counts = report["row_counts"]
    postgres = report["postgres"]
    cdc = report["cdc"]
    print("\nStage 7D verification:")
    print(f"  PostgreSQL version:        {postgres['version']}")
    print(f"  WAL level:                 {postgres['wal_level']}")
    print(f"  Products:                  {counts['product']:,}")
    print(f"  Price-history rows:        {counts['product_price_history']:,}")
    print(f"  Organizations:             {counts['pharmacy_organization']:,}")
    print(f"  Branches:                  {counts['pharmacy_branch']:,}")
    print(f"  POS terminals:             {counts['pos_terminal']:,}")
    print(f"  Product economics:         {counts['product_unit_economics']:,}")
    print(f"  Branch policies:           {counts['branch_commercial_policy']:,}")
    print(f"  CDC publication tables:    {cdc['publication_tables']}")
    print("  CDC replication role:      READY")
    print("  CDC slot/connector:         NOT CREATED YET (Stage 7F)")
    print("  Local database mutation:   YES")
    print("  Cloud mutation:            NO")
    print("\nGenerated files:")
    for name in (
        "database_contract.json",
        "input_row_counts.json",
        "load_verification.json",
        "cdc_readiness.json",
    ):
        print(f"  {OUTPUT_DIR / name}")
    print("\nSTAGE_7D_STATUS=PASS")


if __name__ == "__main__":
    main()
