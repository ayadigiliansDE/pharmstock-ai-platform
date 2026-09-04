from __future__ import annotations

import json
import subprocess
from http.client import RemoteDisconnected
from pathlib import Path
from unittest.mock import patch

from pharmstock.observability.stage7j import (
    EXPECTED_CURRENT_VIEWS,
    EXPECTED_RAW_TABLES,
    CheckResult,
    Stage7JReport,
    check_equal,
    check_storage,
    check_zero,
    render_dashboard,
)
from scripts import run_stage7j


def test_stage7j_contract_uses_26_raw_and_current_objects() -> None:
    assert EXPECTED_RAW_TABLES == 26
    assert EXPECTED_CURRENT_VIEWS == 26


def test_check_equal_and_zero() -> None:
    assert check_equal("x", 3, 3).passed
    assert not check_equal("x", 2, 3).passed
    assert check_zero("dup", 0).passed
    assert not check_zero("dup", 1).passed


def test_storage_guard_is_stricter_than_hard_stop() -> None:
    assert check_storage(7.926, 8.2, 8.5).status == "PASS"
    assert check_storage(8.2, 8.2, 8.5).status == "WARN"
    assert check_storage(8.5, 8.2, 8.5).status == "FAIL"


def test_report_and_dashboard() -> None:
    report = Stage7JReport(
        generated_at="2026-08-26T00:00:00+00:00",
        project_id="demo",
        storage_gib=7.926,
        checks=(CheckResult("x", "PASS", "1", "1"),),
    )
    assert report.status == "PASS"
    html = render_dashboard(report)
    assert "PharmStock Stage 7J" in html
    assert "7.926 GiB" in html


class _HealthyAirflowResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return b'{"metadatabase":{"status":"healthy"},"scheduler":{"status":"healthy"}}'


def test_airflow_wait_retries_remote_disconnect() -> None:
    responses = iter([RemoteDisconnected("starting"), _HealthyAirflowResponse()])

    def fake_urlopen(*args, **kwargs):
        result = next(responses)
        if isinstance(result, BaseException):
            raise result
        return result

    with (
        patch.object(run_stage7j.request, "urlopen", side_effect=fake_urlopen),
        patch.object(run_stage7j.time, "sleep", return_value=None),
    ):
        run_stage7j._wait_for_airflow(timeout_seconds=1)


def test_airflow_compose_declares_explicit_dag_folder() -> None:
    source = Path("infra/docker/docker-compose.stage7j.yml").read_text(encoding="utf-8")
    assert "AIRFLOW__CORE__DAGS_FOLDER: /opt/airflow/dags" in source
    assert "../../dags:/opt/airflow/dags:ro" in source


def test_airflow_dag_inventory_parses_expected_dag() -> None:
    payload = json.dumps(
        [{"dag_id": "pharmstock_stage7j_health", "fileloc": "/opt/airflow/dags/x.py"}]
    )
    completed = subprocess.CompletedProcess([], 0, stdout=payload, stderr="")
    with patch.object(run_stage7j, "_airflow_cli", return_value=completed):
        assert run_stage7j._airflow_dag_ids() == {"pharmstock_stage7j_health"}


def test_stage7j_execute_contract_requires_real_airflow_history() -> None:
    source = Path("scripts/run_stage7j.py").read_text(encoding="utf-8")
    assert "_wait_for_airflow_dag()" in source
    assert "_trigger_airflow_history_run()" in source
    assert "Airflow history run:" in source

def test_airflow_does_not_mutate_dependencies_at_container_startup() -> None:
    source = Path("infra/docker/docker-compose.stage7j.yml").read_text(encoding="utf-8")
    assert "_PIP_ADDITIONAL_REQUIREMENTS" not in source
    assert "google-cloud-bigquery==3.43.0" not in source

