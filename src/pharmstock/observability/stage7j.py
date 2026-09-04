"""Stage 7J observability and data-quality contracts.

The module intentionally keeps the monitoring layer storage-light. BigQuery
checks rely on table metadata where possible and only execute compact aggregate
queries for CDC duplicate/freshness assertions.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pharmstock.cdc.stage7i import DEFAULT_HARD_STOP_GIB, DEFAULT_WARN_GIB
from pharmstock.rebuild.contracts import SNAPSHOT_TABLES

STAGE7J_ROOT: Final[Path] = Path("artifacts/stage7j")
STAGE7J_SUCCESS: Final[Path] = STAGE7J_ROOT / "_SUCCESS"
STAGE7I_READY_MARKER: Final[Path] = Path("artifacts/stage7i/runtime_ready.json")
EXPECTED_RAW_TABLES: Final[int] = len(SNAPSHOT_TABLES)
EXPECTED_RAW_ROWS: Final[int] = 31_954_735
EXPECTED_CURRENT_VIEWS: Final[int] = EXPECTED_RAW_TABLES
EXPECTED_GOLD_MODELS: Final[int] = 3
DEFAULT_WARN_GIB_7J: Final[float] = DEFAULT_WARN_GIB
DEFAULT_HARD_STOP_GIB_7J: Final[float] = DEFAULT_HARD_STOP_GIB


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: str
    observed: str
    expected: str
    severity: str = "ERROR"

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


@dataclass(frozen=True, slots=True)
class Stage7JReport:
    generated_at: str
    project_id: str
    storage_gib: float
    checks: tuple[CheckResult, ...]

    @property
    def status(self) -> str:
        return "PASS" if all(check.passed for check in self.checks) else "FAIL"

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "project_id": self.project_id,
            "storage_gib": self.storage_gib,
            "status": self.status,
            "checks": [asdict(check) for check in self.checks],
        }


def check_equal(name: str, observed: int, expected: int) -> CheckResult:
    return CheckResult(
        name=name,
        status="PASS" if observed == expected else "FAIL",
        observed=f"{observed:,}",
        expected=f"{expected:,}",
    )


def check_zero(name: str, observed: int) -> CheckResult:
    return CheckResult(
        name=name,
        status="PASS" if observed == 0 else "FAIL",
        observed=f"{observed:,}",
        expected="0",
    )


def check_storage(storage_gib: float, warn_gib: float, hard_stop_gib: float) -> CheckResult:
    if storage_gib >= hard_stop_gib:
        status = "FAIL"
    elif storage_gib >= warn_gib:
        status = "WARN"
    else:
        status = "PASS"
    # WARN is intentionally non-passing for acceptance: Stage 7J should surface
    # capacity pressure before downstream stages allocate cloud storage.
    return CheckResult(
        name="bigquery_storage_guard",
        status=status,
        observed=f"{storage_gib:.3f} GiB",
        expected=f"< {warn_gib:.3f} GiB (hard stop {hard_stop_gib:.3f} GiB)",
        severity="CRITICAL",
    )


def write_report(report: Stage7JReport, root: Path = STAGE7J_ROOT) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = report.to_dict()
    (root / "dq_report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    with (root / "health_history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def render_dashboard(report: Stage7JReport) -> str:
    rows = "\n".join(
        "<tr>"
        f"<td>{c.name}</td><td>{c.status}</td><td>{c.observed}</td>"
        f"<td>{c.expected}</td><td>{c.severity}</td>"
        "</tr>"
        for c in report.checks
    )
    return f"""<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><title>PharmStock Stage 7J</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:32px;background:#111827;color:#e5e7eb}}
.card{{background:#1f2937;border-radius:12px;padding:18px;margin-bottom:18px}}
table{{width:100%;border-collapse:collapse;background:#1f2937}}
th,td{{padding:10px;border-bottom:1px solid #374151;text-align:left}}
th{{background:#111827}} .PASS{{color:#34d399}} .WARN{{color:#fbbf24}} .FAIL{{color:#f87171}}
</style></head><body>
<h1>PharmStock Stage 7J — Data Quality & Monitoring</h1>
<div class=\"card\"><b>Status:</b> {report.status}<br><b>Project:</b> {report.project_id}<br>
<b>BigQuery storage:</b> {report.storage_gib:.3f} GiB<br>
<b>Generated:</b> {report.generated_at}</div>
<table><thead><tr><th>Check</th><th>Status</th><th>Observed</th>
<th>Expected</th><th>Severity</th></tr></thead>
<tbody>{rows}</tbody></table></body></html>"""


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
