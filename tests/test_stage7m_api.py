from __future__ import annotations

from pathlib import Path

from pharmstock.onprem.stage7m import (
    STAGE7M_VERSION,
    action_allowed,
    authenticate_api_key,
    stage7m_contract,
)
from scripts.run_checkpoint import checkpoint_command


def test_stage7m_contract_is_governed_and_stops_before_procurement_execution() -> None:
    contract = stage7m_contract()
    assert STAGE7M_VERSION == "0.37.0"
    assert contract["runtime"] == "OPERATIONAL_DECISION_API_AND_WORKBENCH"
    assert contract["governance"]["human_approval_required"] is True
    assert contract["governance"]["automatic_purchase_order_creation"] is False
    assert contract["governance"]["automatic_supplier_selection"] is False
    assert contract["governance"]["purchase_order_endpoint_exists"] is False
    assert contract["governance"]["database_role_has_procurement_write"] is False
    assert contract["cloud_mutation"] is False
    assert contract["bigquery_write"] is False


def test_stage7m_api_key_authentication_maps_to_fixed_principals(monkeypatch) -> None:
    monkeypatch.setenv("PHARMSTOCK_STAGE7M_VIEWER_KEY", "viewer-secret")
    monkeypatch.setenv("PHARMSTOCK_STAGE7M_MANAGER_KEY", "manager-secret")
    viewer = authenticate_api_key("viewer-secret")
    manager = authenticate_api_key("manager-secret")
    assert viewer is not None and viewer.role == "viewer"
    assert manager is not None and manager.role == "manager"
    assert manager.actor_id == "local-manager"


def test_stage7m_invalid_or_blank_api_keys_are_rejected(monkeypatch) -> None:
    monkeypatch.setenv("PHARMSTOCK_STAGE7M_VIEWER_KEY", "known-secret")
    assert authenticate_api_key("") is None
    assert authenticate_api_key("wrong-secret") is None


def test_stage7m_rbac_is_deny_by_default_and_manager_controls_drafts() -> None:
    assert action_allowed("viewer", "acknowledge") is False
    assert action_allowed("operator", "acknowledge") is True
    assert action_allowed("operator", "close") is True
    assert action_allowed("operator", "approve-draft") is False
    assert action_allowed("manager", "approve-draft") is True
    assert action_allowed("manager", "reject") is True
    assert action_allowed("admin", "approve_draft") is True
    assert action_allowed("admin", "unknown") is False


def test_stage7m_schema_creates_narrow_workbench_role_and_stable_read_view() -> None:
    sql = Path("infra/docker/postgres/sql/011_stage7m_workbench_api.sql").read_text(
        encoding="utf-8"
    )
    assert "CREATE ROLE pharmstock_workbench LOGIN" in sql
    assert "CREATE OR REPLACE VIEW decision_ops.v_case_workbench" in sql
    assert "WITH (security_invoker = true)" in sql
    assert "GRANT SELECT ON decision_ops.v_case_workbench TO pharmstock_workbench" in sql
    assert "status, acknowledged_at, decided_at, closed_at, resolution_code, updated_at" in sql
    assert "GRANT INSERT ON decision_ops.decision_audit TO pharmstock_workbench" in sql
    assert "GRANT SELECT, INSERT, UPDATE ON ALL TABLES" not in sql
    assert "GRANT UPDATE ON decision_ops.decision_case" not in sql


def test_stage7m_schema_keeps_operational_audit_append_only() -> None:
    sql = Path("infra/docker/postgres/sql/011_stage7m_workbench_api.sql").read_text(
        encoding="utf-8"
    )
    assert "REVOKE UPDATE, DELETE ON decision_ops.decision_audit FROM pharmstock_decision" in sql
    assert "REVOKE UPDATE, DELETE ON decision_ops.decision_audit FROM pharmstock_workbench" in sql
    assert "GRANT UPDATE ON decision_ops.decision_audit" not in sql
    assert "GRANT DELETE ON decision_ops.decision_audit" not in sql


def test_stage7m_schema_blocks_case_creation_and_procurement_execution() -> None:
    sql = Path("infra/docker/postgres/sql/011_stage7m_workbench_api.sql").read_text(
        encoding="utf-8"
    )
    assert "REVOKE INSERT, DELETE ON decision_ops.decision_case FROM pharmstock_workbench" in sql
    assert "REVOKE INSERT, DELETE ON decision_ops.replenishment_draft" in sql
    assert "REVOKE INSERT, UPDATE, DELETE ON procurement.purchase_order" in sql
    assert "REVOKE INSERT, UPDATE, DELETE ON procurement.goods_receipt" in sql
    assert "GRANT INSERT ON procurement.purchase_order" not in sql


def test_stage7m_api_exposes_only_governed_operational_routes() -> None:
    source = Path("operations/stage7m/api.py").read_text(encoding="utf-8")
    required = (
        '@app.get("/health")',
        '@app.get("/v1/meta")',
        '@app.get("/v1/metrics/summary")',
        '@app.get("/v1/cases")',
        '@app.get("/v1/cases/{case_id}")',
        '@app.post("/v1/cases/{case_id}/actions")',
        '@app.get("/workbench", response_class=HTMLResponse)',
    )
    for marker in required:
        assert marker in source
    lowered = source.lower()
    assert '@app.post("/v1/purchase' not in lowered
    assert '@app.post("/v1/supplier' not in lowered
    assert '@app.post("/v1/receipt' not in lowered


def test_stage7m_api_uses_header_auth_and_server_side_actor_identity() -> None:
    source = Path("operations/stage7m/api.py").read_text(encoding="utf-8")
    assert 'alias="X-PharmStock-Api-Key"' in source
    assert "authenticate_api_key" in source
    assert "principal.actor_id" in source
    assert "X-PharmStock-Actor" not in source
    assert "X-PharmStock-Role" not in source


def test_stage7m_api_uses_locked_transition_and_stage7l_state_machine() -> None:
    source = Path("operations/stage7m/api.py").read_text(encoding="utf-8")
    assert "FOR UPDATE" in source
    assert "next_status(current, action, decision_type)" in source
    assert "INSERT INTO decision_ops.decision_audit" in source
    assert "actor_type, actor_id" in source
    assert "conn.commit()" in source


def test_stage7m_api_never_writes_procurement_tables() -> None:
    source = Path("operations/stage7m/api.py").read_text(encoding="utf-8").lower()
    assert "insert into procurement." not in source
    assert "update procurement." not in source
    assert "delete from procurement." not in source


def test_stage7m_health_checks_upstream_and_database_role_safety() -> None:
    source = Path("operations/stage7m/api.py").read_text(encoding="utf-8")
    assert "STAGE7L_HEARTBEAT" in source
    assert "has_schema_privilege" in source
    assert "has_table_privilege" in source
    assert '"procurement_write_blocked": True' in source
    assert '"automatic_po_creation": False' in source


def test_stage7m_compose_is_loopback_only_and_depends_on_healthy_stage7l() -> None:
    compose = Path("infra/docker/docker-compose.stage7m.yml").read_text(encoding="utf-8")
    assert "pharmstock-stage7m-api:0.37.0" in compose
    assert '"127.0.0.1:8091:8091"' in compose
    assert "PHARMSTOCK_STAGE7M_POSTGRES_USER: pharmstock_workbench" in compose
    assert "PYTHONPATH: /workspace:/workspace/src" in compose
    assert "stage7l-workflow:" in compose
    assert "condition: service_healthy" in compose
    assert "http://localhost:8091/health" in compose
    assert "PHARMSTOCK_BQ_PROJECT" not in compose


def test_stage7m_runner_requires_accepted_stage7l_and_has_safe_dry_run() -> None:
    source = Path("scripts/run_stage7m.py").read_text(encoding="utf-8")
    assert "artifacts/stage7l/stage7l_report.json" in source
    assert "Stage 7L worker was not HEALTHY" in source
    assert "Stage 7L accepted report did not prove blocked PO writes" in source
    assert "Runtime mutation:          NO / DRY RUN" in source
    assert "STAGE_7M_DRY_RUN_STATUS=PASS" in source


def test_stage7m_acceptance_smoke_checks_auth_rbac_and_no_execution_routes() -> None:
    source = Path("scripts/run_stage7m.py").read_text(encoding="utf-8")
    assert '"/v1/cases", expected_status=401' in source
    assert "expected_status=403" in source
    assert '"/openapi.json"' in source
    assert 'mutating_methods = {"post", "put", "patch", "delete"}' in source
    assert '("/v1/cases/{case_id}/actions", "post")' in source
    assert "unexpected mutation routes" in source
    assert '"/workbench"' in source


def test_stage7m_runner_reports_all_acceptance_gates() -> None:
    source = Path("scripts/run_stage7m.py").read_text(encoding="utf-8")
    assert "STAGE_7M_API_STATUS=PASS" in source
    assert "STAGE_7M_RBAC_STATUS=PASS" in source
    assert "STAGE_7M_GOVERNANCE_STATUS=PASS" in source
    assert "STAGE_7M_WORKBENCH_STATUS=PASS" in source
    assert "STAGE_7M_STATUS=PASS" in source


def test_stage7m_workbench_calls_only_governed_case_api() -> None:
    html = Path("operations/stage7m/workbench.html").read_text(encoding="utf-8")
    assert "PharmStock Operational Decision Workbench" in html
    assert "No automatic supplier selection or PO creation" in html
    assert "/v1/metrics/summary" in html
    assert "/v1/cases" in html
    assert "/actions" in html
    assert "/purchase" not in html.lower()


def test_stage7m_assistant_inventory_and_ml_routes_are_read_only() -> None:
    source = Path("operations/stage7m/api.py").read_text(encoding="utf-8")

    assert '@app.get("/v1/assistant/inventory")' in source
    assert '@app.get("/v1/assistant/ml-signals")' in source

    assert '@app.post("/v1/assistant/inventory")' not in source
    assert '@app.post("/v1/assistant/ml-signals")' not in source
    assert '@app.put("/v1/assistant/' not in source
    assert '@app.patch("/v1/assistant/' not in source
    assert '@app.delete("/v1/assistant/' not in source


def test_stage7m_assistant_inventory_uses_governed_serving_view() -> None:
    source = Path("operations/stage7m/api.py").read_text(encoding="utf-8")

    assert "FROM assistant_api.v_inventory_context" in source
    assert "below_reorder" in source
    assert "zero_stock" in source
    assert '"read_only": True' in source


def test_stage7m_assistant_ml_signals_use_governed_serving_view() -> None:
    source = Path("operations/stage7m/api.py").read_text(encoding="utf-8")

    assert "FROM assistant_api.v_ml_signal" in source
    assert "action_required" in source
    assert "severity" in source
    assert "model_key" in source


def test_stage7m_assistant_routes_reuse_api_key_principal_dependency() -> None:
    source = Path("operations/stage7m/api.py").read_text(encoding="utf-8")

    inventory_start = source.index(
        '@app.get("/v1/assistant/inventory")'
    )
    ml_start = source.index(
        '@app.get("/v1/assistant/ml-signals")'
    )
    cases_start = source.index(
        '@app.get("/v1/cases")'
    )

    inventory_block = source[inventory_start:ml_start]
    ml_block = source[ml_start:cases_start]

    assert "PRINCIPAL_DEPENDENCY" in inventory_block
    assert "PRINCIPAL_DEPENDENCY" in ml_block



def test_stage7m_assistant_demand_route_uses_complete_analytical_window() -> None:
    source = Path("operations/stage7m/api.py").read_text(encoding="utf-8")

    assert '@app.get("/v1/assistant/demand")' in source
    assert "FROM assistant_api.v_demand_analytical_as_of" in source
    assert "FROM assistant_api.v_branch_daily_demand" in source
    assert "analytical_as_of_date" in source
    assert "operational_data_as_of" in source
    assert "d.business_date BETWEEN" in source
    assert "a.analytical_as_of_date" in source
    assert '"read_only": True' in source


def test_stage7m_assistant_supplier_route_is_read_only_analytics() -> None:
    source = Path("operations/stage7m/api.py").read_text(encoding="utf-8")

    assert '@app.get("/v1/assistant/suppliers")' in source
    assert "FROM assistant_api.v_supplier_context" in source

    assert '@app.post("/v1/assistant/suppliers")' not in source
    assert '@app.put("/v1/assistant/suppliers")' not in source
    assert '@app.patch("/v1/assistant/suppliers")' not in source
    assert '@app.delete("/v1/assistant/suppliers")' not in source

    assert '"automatic_supplier_selection": False' in source
    assert '"automatic_purchase_order_creation": False' in source


def test_stage7m_assistant_supplier_ranking_has_fixed_metric_allowlist() -> None:
    source = Path("operations/stage7m/api.py").read_text(encoding="utf-8")

    assert '"lead_time":' in source
    assert '"delay_rate":' in source
    assert '"reliability":' in source
    assert "metric must be one of:" in source

    assert "avg_actual_lead_time_days DESC NULLS LAST" in source
    assert "delayed_receipt_rate DESC NULLS LAST" in source
    assert "reliability_score ASC NULLS LAST" in source


def test_stage7m_assistant_demand_and_supplier_routes_require_principal() -> None:
    source = Path("operations/stage7m/api.py").read_text(encoding="utf-8")

    demand_start = source.index(
        '@app.get("/v1/assistant/demand")'
    )
    supplier_start = source.index(
        '@app.get("/v1/assistant/suppliers")'
    )
    cases_start = source.index(
        '@app.get("/v1/cases")'
    )

    demand_block = source[demand_start:supplier_start]
    supplier_block = source[supplier_start:cases_start]

    assert "PRINCIPAL_DEPENDENCY" in demand_block
    assert "PRINCIPAL_DEPENDENCY" in supplier_block



def test_stage7m_checkpoint_is_registered() -> None:
    assert checkpoint_command("7m")[1:] == ["scripts/run_stage7m.py"]
from pathlib import Path


def test_stage7m_assistant_inventory_exposes_split_provenance() -> None:
    source = Path(
        "operations/stage7m/api.py"
    ).read_text(encoding="utf-8")

    start = source.index(
        "FROM assistant_api.v_inventory_context"
    )
    block = source[max(0, start - 1400):start]

    assert "operational_provenance_class" in block
    assert "reference_provenance_class" in block


def test_stage7m_assistant_ml_and_supplier_expose_split_provenance() -> None:
    source = Path(
        "operations/stage7m/api.py"
    ).read_text(encoding="utf-8")

    ml_start = source.index(
        "FROM assistant_api.v_ml_signal"
    )
    ml_block = source[max(0, ml_start - 1400):ml_start]

    supplier_start = source.index(
        "FROM assistant_api.v_supplier_context"
    )
    supplier_block = source[
        max(0, supplier_start - 1800):supplier_start
    ]

    for block in (ml_block, supplier_block):
        assert "operational_provenance_class" in block
        assert "reference_provenance_class" in block


def test_stage7m_cases_inherit_provenance_from_governed_workbench_view() -> None:
    source = Path(
        "operations/stage7m/api.py"
    ).read_text(encoding="utf-8")

    assert (
        "SELECT *\n"
        "        FROM decision_ops.v_case_workbench"
    ) in source

    migration = Path(
        "infra/docker/postgres/sql/"
        "017_stage7o_provenance_serving.sql"
    ).read_text(encoding="utf-8")

    assert (
        "b.provenance_class AS "
        "operational_provenance_class"
    ) in migration or (
        "END AS operational_provenance_class"
    ) in migration

    assert (
        "p.provenance_class AS "
        "reference_provenance_class"
    ) in migration


def test_stage7o_provenance_migration_preserves_least_privilege() -> None:
    sql = Path(
        "infra/docker/postgres/sql/"
        "017_stage7o_provenance_serving.sql"
    ).read_text(encoding="utf-8")

    assert (
        "GRANT SELECT (provenance_class)\n"
        "ON master.pharmacy_branch\n"
        "TO pharmstock_workbench"
    ) in sql

    assert (
        "GRANT SELECT (provenance_class)\n"
        "ON master.product\n"
        "TO pharmstock_workbench"
    ) in sql

    assert (
        "GRANT SELECT (provenance_class)\n"
        "ON inventory.stock_batch\n"
        "TO pharmstock_workbench"
    ) in sql

    assert (
        "GRANT SELECT ON master.pharmacy_branch "
        "TO pharmstock_workbench"
    ) not in sql

    assert (
        "GRANT SELECT ON master.product "
        "TO pharmstock_workbench"
    ) not in sql

    assert (
        "GRANT SELECT ON inventory.stock_batch "
        "TO pharmstock_workbench"
    ) not in sql

    assert (
        "GRANT INSERT ON procurement.purchase_order"
    ) not in sql
