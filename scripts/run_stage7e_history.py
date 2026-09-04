"""Generate and verify Stage 7E high-fidelity historical POS operations in PostgreSQL."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from dataclasses import asdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pharmstock.simulation.pos_history import (
    CUSTOMERS_PER_BRANCH,
    DEFAULT_END_DATE,
    HISTORY_MODEL_VERSION,
    HOUSEHOLDS_PER_BRANCH,
    PATIENTS_PER_HOUSEHOLD,
    HistoryProfile,
    HistoryRunContract,
    resolve_profile,
    run_token,
    write_history_contract,
)

COMPOSE_FILE = Path("infra/docker/docker-compose.postgres.yml")
SUPPORT_SQL = "/opt/pharmstock/infra/docker/postgres/sql/005_stage7e_support.sql"
GENERATE_SQL = "/opt/pharmstock/infra/docker/postgres/sql/006_generate_stage7e_history.sql"
VERIFY_SQL = "/opt/pharmstock/infra/docker/postgres/sql/007_verify_stage7e_history.sql"
FINALIZE_SQL = "/opt/pharmstock/infra/docker/postgres/sql/008_finalize_stage7e_metrics.sql"
OUTPUT_DIR = Path("artifacts/stage7e")
STAGE7D_SUCCESS = Path("artifacts/stage7d/_SUCCESS")


class Stage7EExecutionError(RuntimeError):
    """Raised when the local historical workload fails acceptance."""


def _run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, capture_output=capture)


def _compose(*args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return _run(["docker", "compose", "-f", str(COMPOSE_FILE), *args], capture=capture)


def _psql_file(path: str, contract: HistoryRunContract | None = None) -> None:
    variable_args = ""
    if contract is not None:
        variable_args = (
            f" -v run_token={run_token(contract)}"
            f" -v profile={contract.profile}"
            f" -v model_version={HISTORY_MODEL_VERSION}"
            f" -v seed={contract.seed}"
            f" -v start_date={contract.start_date}"
            f" -v end_date={contract.end_date}"
            f" -v branch_limit={contract.branch_limit}"
            f" -v days={contract.days}"
            f" -v base_transactions={contract.base_transactions_per_branch_day}"
        )
    shell = (
        'PGPASSWORD="$POSTGRES_PASSWORD" psql -v ON_ERROR_STOP=1 '
        '-U "$POSTGRES_USER" -d "$POSTGRES_DB"'
        f"{variable_args} -f \"{path}\""
    )
    _compose("exec", "-T", "postgres", "bash", "-lc", shell)


def _psql_query(sql: str) -> str:
    shell = (
        'PGPASSWORD="$POSTGRES_PASSWORD" psql -v ON_ERROR_STOP=1 -At '
        '-U "$POSTGRES_USER" -d "$POSTGRES_DB" '
        f'-c "{sql}"'
    )
    result = _compose("exec", "-T", "postgres", "bash", "-lc", shell, capture=True)
    return result.stdout.strip()


def _verify_output(contract: HistoryRunContract) -> dict[str, str]:
    token = run_token(contract)
    shell = (
        'PGPASSWORD="$POSTGRES_PASSWORD" psql -v ON_ERROR_STOP=1 '
        '-U "$POSTGRES_USER" -d "$POSTGRES_DB" '
        f"-v run_token={token} -v start_date={contract.start_date} "
        f"-v end_date={contract.end_date} -f \"{VERIFY_SQL}\""
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


def _integer(values: dict[str, str], key: str) -> int:
    try:
        return int(values[key])
    except (KeyError, ValueError) as exc:
        raise Stage7EExecutionError(f"invalid Stage 7E verification integer: {key}") from exc


def _decimal(values: dict[str, str], key: str) -> Decimal:
    try:
        return Decimal(values[key])
    except (KeyError, InvalidOperation) as exc:
        raise Stage7EExecutionError(f"invalid Stage 7E verification decimal: {key}") from exc


def _database_size_bytes() -> int:
    value = _psql_query("SELECT pg_database_size(current_database());")
    try:
        return int(value)
    except ValueError as exc:
        raise Stage7EExecutionError("could not read PostgreSQL database size") from exc


def _validate(
    values: dict[str, str],
    contract: HistoryRunContract,
    *,
    db_size_before: int,
    db_size_after: int,
    elapsed_seconds: float,
) -> dict[str, object]:
    sale_headers = _integer(values, "sale_header")
    sale_lines = _integer(values, "sale_line")
    payments = _integer(values, "payment")
    demand_attempts = _integer(values, "demand_attempt")
    partial_demand_attempts = _integer(values, "partial_demand_attempts")
    stockout_demand_attempts = _integer(values, "stockout_demand_attempts")
    lost_demand_units = _integer(values, "lost_demand_units")
    returns = _integer(values, "return_header")
    batches = _integer(values, "batch_rows")
    inventory_positions = _integer(values, "inventory_positions")
    purchase_orders = _integer(values, "purchase_orders")
    goods_receipts = _integer(values, "goods_receipts")
    delayed_goods_receipts = _integer(values, "delayed_goods_receipts")
    return_rate = _decimal(values, "return_rate")
    avg_lines = _decimal(values, "avg_lines_per_sale")
    net_sales = _decimal(values, "net_sales_egp")
    cogs = _decimal(values, "cogs_egp")
    gross_profit = _decimal(values, "gross_profit_egp")
    customers = _integer(values, "customers")
    households = _integer(values, "households")
    loyalty_accounts = _integer(values, "loyalty_accounts")
    patients = _integer(values, "patients")
    known_sales = _integer(values, "known_sales")
    anonymous_sales = _integer(values, "anonymous_sales")
    loyalty_sales = _integer(values, "loyalty_sales")
    prescription_sales = _integer(values, "prescription_sales")
    prescription_contexts = _integer(values, "prescription_contexts")
    chronic_repeat_sales = _integer(values, "chronic_repeat_sales")
    delivery_registered_sales = _integer(values, "delivery_registered_sales")

    known_ratio = Decimal(known_sales) / Decimal(sale_headers)
    loyalty_ratio = Decimal(loyalty_accounts) / Decimal(customers)
    checks = {
        "run_status_ready": values.get("run_status") in {"RUNNING", "PASS"},
        "profile_matches": values.get("run_profile") == contract.profile,
        "model_version_matches": values.get("run_model_version") == HISTORY_MODEL_VERSION,
        "fast_audit_strategy": (
            values.get("audit_strategy") == "FAST_STAGING_METRICS_NO_FULL_TABLE_RESCAN"
        ),
        "sale_header_scale": sale_headers >= contract.min_sale_headers,
        "sale_line_scale": sale_lines >= contract.min_sale_lines,
        "payments_one_per_sale": payments == sale_headers,
        "demand_attempt_per_sale_line": demand_attempts >= sale_lines,
        "partial_demand_present": partial_demand_attempts > 0,
        "stockout_demand_present": stockout_demand_attempts > 0,
        "lost_demand_present": lost_demand_units > 0,
        "return_lines_match_headers": _integer(values, "return_line") == returns,
        "branch_scope_complete": _integer(values, "branches") == contract.branch_limit,
        "all_governorates_covered": (
            _integer(values, "governorates") == 27 if contract.branch_limit >= 27 else True
        ),
        "multiple_channels": _integer(values, "channels") >= 2,
        "payment_mix_present": _integer(values, "payment_methods") >= 3,
        "basket_line_distribution": Decimal("1.40") <= avg_lines <= Decimal("2.30"),
        "positive_net_sales": net_sales > 0,
        "positive_cogs": cogs > 0,
        "positive_gross_profit": gross_profit > 0,
        "header_finance_protected_by_constraint": _integer(values, "header_financial_guard") >= 1,
        "line_finance_protected_by_constraint": _integer(values, "line_financial_guard") >= 1,
        "demand_arithmetic_protected_by_constraint": (
            _integer(values, "demand_arithmetic_guard") >= 1
        ),
        "inventory_nonnegative_protected_by_constraint": (
            _integer(values, "inventory_nonnegative_guard") >= 1
        ),
        "payment_uniqueness_protected": _integer(values, "payment_unique_guard") >= 1,
        "all_sale_lines_batched": _integer(values, "lines_without_batch") == 0,
        "inventory_positions_match_batches": inventory_positions == batches,
        "sale_movement_per_line": _integer(values, "sale_movements") == sale_lines,
        "opening_movement_per_batch": _integer(values, "opening_receipt_movements") == batches,
        "supplier_network_created": _integer(values, "suppliers") >= 300,
        "opening_po_per_branch": purchase_orders == contract.branch_limit,
        "opening_receipt_per_branch": goods_receipts == contract.branch_limit,
        "supplier_delay_mix_present": 0 < delayed_goods_receipts < goods_receipts,
        "po_lines_match_batches": _integer(values, "purchase_order_lines") == batches,
        "receipt_lines_match_batches": _integer(values, "goods_receipt_lines") == batches,
        "realistic_low_return_rate": Decimal("0.002") <= return_rate <= Decimal("0.012"),
        "customer_profiles_per_branch": customers == contract.branch_limit * CUSTOMERS_PER_BRANCH,
        "households_per_branch": households == contract.branch_limit * HOUSEHOLDS_PER_BRANCH,
        "patients_per_branch": (
            patients
            == contract.branch_limit * HOUSEHOLDS_PER_BRANCH * PATIENTS_PER_HOUSEHOLD
        ),
        "loyalty_population_realistic": Decimal("0.35") <= loyalty_ratio <= Decimal("0.55"),
        "known_and_anonymous_reconcile": known_sales + anonymous_sales == sale_headers,
        "known_customer_mix_realistic": Decimal("0.50") <= known_ratio <= Decimal("0.85"),
        "loyalty_sales_present": loyalty_sales > 0,
        "delivery_registered_sales_present": delivery_registered_sales > 0,
        "prescription_sales_present": prescription_sales > 0,
        "prescription_context_one_per_prescription": prescription_contexts == prescription_sales,
        "chronic_repeat_behavior_present": chronic_repeat_sales > 0,
        "customer_context_constraint_present": _integer(values, "sale_customer_context_guard") >= 1,
        "prescription_identity_constraint_present": (
            _integer(values, "prescription_identity_guard") >= 1
        ),
        "no_direct_identifier_columns": _integer(values, "customer_direct_identifier_columns") == 0,
        "privacy_false_guards_present": _integer(values, "privacy_false_guard") >= 2,
        "database_size_readable": db_size_after > 0,
    }
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise Stage7EExecutionError("Stage 7E checks failed: " + ", ".join(failed))

    return {
        "status": "PASS",
        "contract": asdict(contract),
        "run_token": run_token(contract),
        "checks": checks,
        "row_counts": {
            "sale_header": sale_headers,
            "sale_line": sale_lines,
            "payment": payments,
            "demand_attempt": demand_attempts,
            "partial_demand_attempt": partial_demand_attempts,
            "stockout_demand_attempt": stockout_demand_attempts,
            "return_header": returns,
            "return_line": _integer(values, "return_line"),
            "stock_batch": batches,
            "inventory_position": inventory_positions,
            "sale_stock_movement": _integer(values, "sale_movements"),
            "opening_receipt_movement": _integer(values, "opening_receipt_movements"),
            "supplier": _integer(values, "suppliers"),
            "purchase_order": purchase_orders,
            "purchase_order_line": _integer(values, "purchase_order_lines"),
            "goods_receipt": goods_receipts,
            "delayed_goods_receipt": delayed_goods_receipts,
            "goods_receipt_line": _integer(values, "goods_receipt_lines"),
            "customer_profile": customers,
            "household": households,
            "loyalty_account": loyalty_accounts,
            "patient_profile": patients,
            "prescription_context": prescription_contexts,
        },
        "business_metrics": {
            "branches": _integer(values, "branches"),
            "governorates": _integer(values, "governorates"),
            "channels": _integer(values, "channels"),
            "payment_methods": _integer(values, "payment_methods"),
            "avg_lines_per_sale": str(avg_lines),
            "return_rate": str(return_rate),
            "lost_demand_units": lost_demand_units,
            "gross_sales_egp": values["gross_sales_egp"],
            "net_sales_egp": values["net_sales_egp"],
            "cogs_egp": values["cogs_egp"],
            "gross_profit_egp": values["gross_profit_egp"],
            "known_sales": known_sales,
            "anonymous_sales": anonymous_sales,
            "loyalty_sales": loyalty_sales,
            "delivery_registered_sales": delivery_registered_sales,
            "prescription_sales": prescription_sales,
            "chronic_repeat_sales": chronic_repeat_sales,
            "known_customer_ratio": str(known_ratio.quantize(Decimal("0.0001"))),
        },
        "runtime": {
            "elapsed_seconds": round(elapsed_seconds, 3),
            "database_size_before_bytes": db_size_before,
            "database_size_after_bytes": db_size_after,
            "database_growth_bytes": db_size_after - db_size_before,
            "audit_strategy": values["audit_strategy"],
        },
        "truth_boundary": {
            "pos_and_operational_history": "SYNTHETIC_CALIBRATED",
            "product_and_retail_price": "PUBLIC_MARKET_EGYPT",
            "customer_behavior": "SYNTHETIC_CALIBRATED_PRIVACY_SAFE",
            "customer_direct_identifiers_generated": False,
            "patient_identifiers": "SYNTHETIC_PSEUDONYMOUS",
        },
        "local_database_mutation_performed": True,
        "cloud_mutation_performed": False,
    }

def _write_outputs(report: dict[str, object], contract: HistoryRunContract) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_history_contract(OUTPUT_DIR / "history_contract.json", contract)
    (OUTPUT_DIR / "history_run_profile.json").write_text(
        json.dumps(asdict(contract), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "history_verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "table_counts.json").write_text(
        json.dumps(report["row_counts"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "_SUCCESS").write_text("STAGE_7E_STATUS=PASS\n", encoding="utf-8")


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def _existing_run_status(contract: HistoryRunContract) -> str:
    token = run_token(contract)
    return _psql_query(
        "SELECT coalesce((SELECT status FROM audit.simulation_run "
        f"WHERE run_token = '{token}'), 'NONE');"
    )


def _run_baseline_size(contract: HistoryRunContract) -> int:
    token = run_token(contract)
    value = _psql_query(
        "SELECT coalesce(baseline_database_size_bytes, 0) "
        f"FROM audit.simulation_run WHERE run_token = '{token}';"
    )
    try:
        return int(value)
    except ValueError as exc:
        raise Stage7EExecutionError("could not read Stage 7E baseline database size") from exc


def _mark_run_pass(contract: HistoryRunContract) -> None:
    token = run_token(contract)
    _psql_query(
        "UPDATE audit.simulation_run SET status = 'PASS', completed_at = now() "
        f"WHERE run_token = '{token}' AND status = 'RUNNING' RETURNING status;"
    )


def _ensure_postgres_ready() -> None:
    result = _compose(
        "exec",
        "-T",
        "postgres",
        "pg_isready",
        "-U",
        "pharmstock_admin",
        "-d",
        "pharmstock_ops",
        capture=True,
    )
    if "accepting connections" not in result.stdout:
        raise Stage7EExecutionError("Stage 7D PostgreSQL is not accepting connections")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Stage 7E historical POS workload")
    parser.add_argument(
        "--profile",
        choices=tuple(item.value for item in HistoryProfile),
        default=HistoryProfile.ACCEPTANCE.value,
    )
    parser.add_argument("--end-date", type=_parse_date, default=DEFAULT_END_DATE)
    parser.add_argument("--days", type=int)
    parser.add_argument("--branches", type=int)
    parser.add_argument("--base-transactions", type=int)
    parser.add_argument(
        "--allow-large-run",
        action="store_true",
        help="Required for the 365-day prod_like workload.",
    )
    args = parser.parse_args()

    profile = HistoryProfile(args.profile)
    if profile is HistoryProfile.PROD_LIKE and not args.allow_large_run:
        raise SystemExit(
            "prod_like requires --allow-large-run because it can create "
            "tens of millions of rows"
        )
    if shutil.which("docker") is None:
        raise SystemExit("Docker CLI is required for Stage 7E")
    if not STAGE7D_SUCCESS.is_file():
        raise SystemExit("Stage 7E requires artifacts/stage7d/_SUCCESS")

    contract = resolve_profile(
        profile,
        end_date=args.end_date,
        days=args.days,
        branch_limit=args.branches,
        base_transactions_per_branch_day=args.base_transactions,
    )
    token = run_token(contract)

    print("=== PharmStock V2 / Stage 7E High-Fidelity Historical POS Simulator ===")
    print(f"Profile:                         {contract.profile}")
    print(f"Run token:                       {token}")
    print(f"History window:                  {contract.start_date} -> {contract.end_date}")
    print(f"Branches:                        {contract.branch_limit:,}")
    print(f"Days:                            {contract.days:,}")
    print(
        "Base transactions/branch/day:    "
        f"{contract.base_transactions_per_branch_day:,} x demand_index"
    )
    print(f"Minimum accepted sale headers:   {contract.min_sale_headers:,}")
    print(f"Minimum accepted sale lines:     {contract.min_sale_lines:,}")
    print("Transaction provenance:          SYNTHETIC_CALIBRATED")
    print("Product/retail-price provenance: PUBLIC_MARKET_EGYPT")
    print("Customer behavior simulation:     YES (privacy-safe)")
    print("Customer direct PII generated:     NO")
    print("Cloud mutation:                  NO")

    try:
        _ensure_postgres_ready()
        _psql_file(SUPPORT_SQL)
        existing = _existing_run_status(contract)
        if existing == "NONE":
            db_size_before = _database_size_bytes()
            print("Generating historical operational workload...", flush=True)
            started = time.monotonic()
            _psql_file(GENERATE_SQL, contract)
            print("History committed. Finalizing fast audit metrics...", flush=True)
            _psql_file(FINALIZE_SQL, contract)
            elapsed = time.monotonic() - started
        elif existing == "RUNNING":
            db_size_before = _run_baseline_size(contract)
            print(
                "Resuming Stage 7E from committed RUNNING history; "
                "skipping regeneration...",
                flush=True,
            )
            started = time.monotonic()
            _psql_file(FINALIZE_SQL, contract)
            elapsed = time.monotonic() - started
        elif existing == "PASS":
            db_size_before = _run_baseline_size(contract)
            print("Existing PASS run found; verifying cached fast audit metrics...", flush=True)
            started = time.monotonic()
            elapsed = time.monotonic() - started
        else:
            raise Stage7EExecutionError(f"unsupported Stage 7E run status: {existing}")
        db_size_after = _database_size_bytes()
        values = _verify_output(contract)
        report = _validate(
            values,
            contract,
            db_size_before=db_size_before,
            db_size_after=db_size_after,
            elapsed_seconds=elapsed,
        )
        if existing != "PASS":
            _mark_run_pass(contract)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"Stage 7E Docker/PostgreSQL command failed with code {exc.returncode}"
        ) from exc
    except Stage7EExecutionError as exc:
        raise SystemExit(str(exc)) from exc

    _write_outputs(report, contract)
    counts = report["row_counts"]
    metrics = report["business_metrics"]
    runtime = report["runtime"]
    print("\nStage 7E verification:")
    print(f"  Sale headers:              {counts['sale_header']:,}")
    print(f"  Sale lines:                {counts['sale_line']:,}")
    print(f"  Payments:                  {counts['payment']:,}")
    print(f"  Demand attempts:           {counts['demand_attempt']:,}")
    print(f"  Partial-demand attempts:   {counts['partial_demand_attempt']:,}")
    print(f"  Stockout demand attempts:  {counts['stockout_demand_attempt']:,}")
    print(f"  Lost-demand units:         {metrics['lost_demand_units']:,}")
    print(f"  Returns:                   {counts['return_header']:,}")
    print(f"  Customer profiles:         {counts['customer_profile']:,}")
    print(f"  Households:                {counts['household']:,}")
    print(f"  Loyalty accounts:          {counts['loyalty_account']:,}")
    print(f"  Patient profiles:          {counts['patient_profile']:,}")
    print(f"  Prescription contexts:     {counts['prescription_context']:,}")
    print(f"  Stock batches:             {counts['stock_batch']:,}")
    print(f"  Inventory positions:       {counts['inventory_position']:,}")
    print(f"  Sale stock movements:      {counts['sale_stock_movement']:,}")
    print(f"  Suppliers:                 {counts['supplier']:,}")
    print(f"  Purchase orders:           {counts['purchase_order']:,}")
    print(f"  Goods receipts:            {counts['goods_receipt']:,}")
    print(f"  Delayed goods receipts:    {counts['delayed_goods_receipt']:,}")
    print(f"  Branches represented:      {metrics['branches']:,}")
    print(f"  Governorates represented:  {metrics['governorates']}/27")
    print(f"  Avg lines / sale:          {metrics['avg_lines_per_sale']}")
    print(f"  Return rate:               {metrics['return_rate']}")
    print(f"  Known customer ratio:      {metrics['known_customer_ratio']}")
    print(f"  Chronic-repeat sales:      {metrics['chronic_repeat_sales']:,}")
    print(f"  Net sales (EGP):           {metrics['net_sales_egp']}")
    print(f"  Gross profit (EGP):        {metrics['gross_profit_egp']}")
    print(f"  Runtime seconds:           {runtime['elapsed_seconds']}")
    print(f"  DB growth bytes:           {runtime['database_growth_bytes']:,}")
    print("  Local database mutation:   YES")
    print("  Cloud mutation:            NO")
    print("\nGenerated files:")
    for name in (
        "history_contract.json",
        "history_run_profile.json",
        "history_verification.json",
        "table_counts.json",
    ):
        print(f"  {OUTPUT_DIR / name}")
    print("\nSTAGE_7E_STATUS=PASS")


if __name__ == "__main__":
    main()
