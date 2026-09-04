from __future__ import annotations

import csv
import json
from pathlib import Path

from pharmstock.analytics.dimensions_stage import (
    DIMENSION_MODELS,
    MASTER_STAGING_MODELS,
    STAGE5D_RELATIONSHIP_TESTS,
    inspect_stage5d_dimensions,
)
from pharmstock.masterdata.bigquery_cloud import (
    duplicate_primary_key_sql,
    final_table_ddl,
    load_plan_from_snapshot,
    null_violation_sql,
)
from pharmstock.masterdata.stage5d import (
    BIGQUERY_CLUSTER_FIELDS,
    MASTER_TABLES,
    prepare_master_snapshot,
)


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _seed_stage5d_inputs(root: Path) -> None:
    (root / "artifacts/stage2d").mkdir(parents=True)
    (root / "artifacts/stage2d/_SUCCESS").write_text("ok\n", encoding="utf-8")
    (root / "artifacts/stage2d/inventory_manifest.json").write_text(
        json.dumps(
            {
                "seed": 20260822,
                "branch_count": 3,
                "catalog_products_available": 2,
            }
        ),
        encoding="utf-8",
    )
    product_fields = [
        "product_id",
        "display_name",
        "brand_name",
        "generic_name",
        "dosage_form",
        "routes",
        "active_ingredients",
        "package_description",
        "manufacturer",
        "prescription_status",
        "regulatory_status",
        "market_code",
        "rxnorm_rxcui",
        "ndc_product_code",
        "ndc_package_code",
        "source_system",
        "source_record_id",
        "source_updated_at",
    ]
    _write_csv(
        root / "artifacts/stage2b-5000/drug_catalog.csv",
        product_fields,
        [
            {
                "product_id": "00000000-0000-0000-0000-000000000001",
                "display_name": "Product A",
                "brand_name": "A",
                "generic_name": "Gen A",
                "dosage_form": "TABLET",
                "routes": "ORAL",
                "active_ingredients": "Ingredient A 10 mg",
                "package_description": "Bottle",
                "manufacturer": "Maker A",
                "prescription_status": "prescription",
                "regulatory_status": "active",
                "market_code": "US",
                "rxnorm_rxcui": "1",
                "ndc_product_code": "001",
                "ndc_package_code": "001-01",
                "source_system": "openfda_ndc",
                "source_record_id": "a",
                "source_updated_at": "2026-08-21T00:00:00+00:00",
            },
            {
                "product_id": "00000000-0000-0000-0000-000000000002",
                "display_name": "Product B",
                "brand_name": "",
                "generic_name": "Gen B",
                "dosage_form": "CAPSULE",
                "routes": "ORAL",
                "active_ingredients": "Ingredient B 20 mg",
                "package_description": "Box",
                "manufacturer": "Maker B",
                "prescription_status": "otc",
                "regulatory_status": "active",
                "market_code": "US",
                "rxnorm_rxcui": "",
                "ndc_product_code": "002",
                "ndc_package_code": "002-01",
                "source_system": "openfda_ndc",
                "source_record_id": "b",
                "source_updated_at": "",
            },
        ],
    )
    supplier_fields = [
        "supplier_id",
        "supplier_code",
        "display_name",
        "supplier_type",
        "market_code",
        "base_lead_time_days",
        "service_regions",
        "service_governorates",
        "catalog_coverage_pct",
        "expected_fill_rate_pct",
        "reliability_score_pct",
        "cycle_capacity_units",
        "cold_chain_supported",
        "synthetic_record",
    ]
    _write_csv(
        root / "artifacts/stage2f1/supplier_master.csv",
        supplier_fields,
        [
            {
                "supplier_id": "10000000-0000-0000-0000-000000000001",
                "supplier_code": "SUP-001",
                "display_name": "Synthetic Supplier",
                "supplier_type": "national_distributor",
                "market_code": "EG",
                "base_lead_time_days": 2,
                "service_regions": "all",
                "service_governorates": "Cairo",
                "catalog_coverage_pct": 90,
                "expected_fill_rate_pct": 95,
                "reliability_score_pct": 96,
                "cycle_capacity_units": 10000,
                "cold_chain_supported": True,
                "synthetic_record": True,
            }
        ],
    )
    (root / "artifacts/stage2f1/_SUCCESS").write_text("ok\n", encoding="utf-8")
    (root / "artifacts/stage5c").mkdir(parents=True)
    (root / "artifacts/stage5c/cloud_execution_report.json").write_text(
        json.dumps({"cloud_mutation": True}), encoding="utf-8"
    )


def test_prepare_master_snapshot_is_local_and_lineage_safe(tmp_path: Path, monkeypatch) -> None:
    _seed_stage5d_inputs(tmp_path)
    monkeypatch.chdir(tmp_path)
    report = prepare_master_snapshot()

    assert report["cloud_mutation"] is False
    assert report["table_counts"]["product_master"] == 2
    assert report["table_counts"]["pharmacy_branch_master"] == 3
    assert report["table_counts"]["supplier_master"] == 1
    assert report["source_lineage"]["product_master"]["source_market"] == "US"
    assert report["monetary_measures_generated"] is False
    assert (tmp_path / "artifacts/stage5d/_SUCCESS").is_file()


def test_master_ready_files_have_explicit_origins(tmp_path: Path, monkeypatch) -> None:
    _seed_stage5d_inputs(tmp_path)
    monkeypatch.chdir(tmp_path)
    prepare_master_snapshot()
    product = (tmp_path / "artifacts/stage5d/master_ready/product_master.csv").read_text(
        encoding="utf-8-sig"
    )
    branch = (
        tmp_path / "artifacts/stage5d/master_ready/pharmacy_branch_master.csv"
    ).read_text(encoding="utf-8-sig")
    supplier = (tmp_path / "artifacts/stage5d/master_ready/supplier_master.csv").read_text(
        encoding="utf-8-sig"
    )
    assert "official_openfda_ndc" in product
    assert "synthetic_egypt_pharmacy_network" in branch
    assert "synthetic_supplier_network" in supplier
    assert "revenue" not in product.lower()
    assert "unit_price" not in product.lower()


def test_master_contract_has_four_tables_and_clustering() -> None:
    assert MASTER_TABLES == (
        "product_master",
        "pharmacy_organization_master",
        "pharmacy_branch_master",
        "supplier_master",
    )
    assert BIGQUERY_CLUSTER_FIELDS["pharmacy_branch_master"][0] == "governorate"
    assert "supplier_type" in BIGQUERY_CLUSTER_FIELDS["supplier_master"]


def test_final_master_ddl_preserves_required_contract() -> None:
    ddl = final_table_ddl(
        "project-x",
        "pharmstock_master",
        "product_master",
        "project-x.pharmstock_master.__stage",
    )
    assert "CREATE OR REPLACE TABLE" in ddl
    assert "`product_id` STRING NOT NULL" in ddl
    assert "CLUSTER BY `dosage_form`, `prescription_status`, `manufacturer`" in ddl
    assert "AS SELECT * FROM `project-x.pharmstock_master.__stage`" in ddl


def test_master_validation_sql_checks_nulls_and_duplicate_primary_keys() -> None:
    null_sql = null_violation_sql("p.d.stage", "supplier_master")
    duplicate_sql = duplicate_primary_key_sql("p.d.supplier_master", "supplier_master")
    assert "supplier_id` IS NULL" in null_sql
    assert "GROUP BY `supplier_id` HAVING COUNT(*) > 1" in duplicate_sql


def test_load_plan_requires_completed_snapshot(tmp_path: Path) -> None:
    try:
        load_plan_from_snapshot(
            snapshot_root=tmp_path,
            project_id="p",
            dataset_id="d",
            location="EU",
        )
    except RuntimeError as exc:
        assert "Completed Stage 5D" in str(exc)
    else:
        raise AssertionError("incomplete snapshot must fail")


def test_dbt_stage5d_models_and_relationship_tests_exist() -> None:
    root = Path("dbt/pharmstock_analytics")
    master_models = {path.stem for path in (root / "models/master_staging").glob("*.sql")}
    dimensions = {path.stem for path in (root / "models/dimensions").glob("*.sql")}
    tests = {path.stem for path in (root / "tests").glob("*.sql")}
    assert master_models == set(MASTER_STAGING_MODELS)
    assert dimensions == set(DIMENSION_MODELS)
    assert set(STAGE5D_RELATIONSHIP_TESTS).issubset(tests)


def test_stage5d_dbt_inspection_is_deterministic(monkeypatch, tmp_path: Path) -> None:
    cloud = tmp_path / "stage5d"
    cloud.mkdir()
    (cloud / "cloud_execution_report.json").write_text(
        json.dumps({"cloud_mutation": True}), encoding="utf-8"
    )
    monkeypatch.setenv("PHARMSTOCK_BQ_PROJECT", "project-x")
    monkeypatch.setenv("PHARMSTOCK_BQ_MASTER_DATASET", "pharmstock_master")
    readiness = inspect_stage5d_dimensions(stage5d_root=cloud, installed=True)
    assert readiness.project_files_ready is True
    assert readiness.cloud_ready_hint is True
    assert readiness.dimension_model_count == 3
    assert readiness.relationship_test_count == 5


def test_stage5d_scripts_are_explicitly_guarded() -> None:
    master_script = Path("scripts/run_stage5d_bigquery.py").read_text(encoding="utf-8")
    dimension_script = Path("scripts/run_stage5d_dimensions.py").read_text(encoding="utf-8")
    assert "--execute" in master_script
    assert "--replace" in master_script
    assert "NO / DRY RUN" in master_script
    assert "--execute" in dimension_script
    assert "NO / DRY RUN" in dimension_script


def test_stage5d_powerbi_dimensions_do_not_add_monetary_measures() -> None:
    root = Path("dbt/pharmstock_analytics/models/dimensions")
    sql = "\n".join(path.read_text(encoding="utf-8").lower() for path in root.glob("*.sql"))
    for token in ("revenue", "unit_price", "unit_cost", "gross_margin"):
        assert token not in sql
