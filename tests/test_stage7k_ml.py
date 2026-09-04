from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from pharmstock.ml.cloud_ready import cloud_ready_plan
from pharmstock.ml.offline_history import (
    OFFLINE_HISTORY_PROVENANCE,
    build_demand_history,
    build_stockout_history,
)
from pharmstock.ml.stage7k import (
    DEMAND_HORIZONS_DAYS,
    MODEL_SPECS,
    STAGE7K_VERSION,
    Stage7KConfig,
    demand_calibration_seed_sql,
    expiry_feature_sql,
    expiry_risk_score,
    history_coverage_sql,
    inventory_policy_feature_sql,
    product_temporal_feature_sql,
    reorder_feature_sql,
    reorder_recommendation_units,
    stage7k_contract,
    stockout_calibration_seed_sql,
    stockout_risk_score,
    stockout_supervised_feature_sql,
    storage_status,
)
from scripts.run_checkpoint import checkpoint_command


def _config() -> Stage7KConfig:
    return Stage7KConfig(
        project_id="unit-test-project",
        gold_dataset="gold",
        current_dataset="current",
        location="EU",
        mlflow_uri="http://localhost:5001",
        serving_uri="http://localhost:8090",
        max_training_rows=10_000,
        max_query_gib=8.0,
        warn_gib=8.2,
        hard_stop_gib=8.5,
    )


def test_stage7k_has_four_realistic_components() -> None:
    assert len(MODEL_SPECS) == 4
    assert len({spec.key for spec in MODEL_SPECS}) == 4
    assert len({spec.registered_name for spec in MODEL_SPECS}) == 4
    assert {spec.model_kind for spec in MODEL_SPECS} == {
        "predictive_ml",
        "predictive_risk_ml",
        "service_level_replenishment_policy",
        "probabilistic_sell_through_policy",
    }
    assert DEMAND_HORIZONS_DAYS == (1, 7, 14, 30)


def test_stage7k_bigquery_sql_is_read_only() -> None:
    config = _config()
    sql_blocks = (
        product_temporal_feature_sql(config),
        stockout_supervised_feature_sql(config),
        inventory_policy_feature_sql(config),
        reorder_feature_sql(config),
        expiry_feature_sql(config),
    )
    forbidden = (
        "CREATE TABLE",
        "CREATE OR REPLACE",
        "INSERT INTO",
        "MERGE ",
        "UPDATE ",
        "DELETE ",
    )
    for sql in sql_blocks:
        upper = sql.upper()
        assert upper.startswith("WITH ")
        assert not any(token in upper for token in forbidden)


def test_demand_query_preserves_full_time_axis_and_multi_horizon_targets() -> None:
    sql = product_temporal_feature_sql(_config()).upper()
    assert "FARM_FINGERPRINT(CAST(PRODUCT_ID AS STRING))" in sql
    assert "TARGET_DEMAND_1D" in sql
    assert "TARGET_DEMAND_7D" in sql
    assert "TARGET_DEMAND_14D" in sql
    assert "TARGET_DEMAND_30D" in sql
    assert "RANGE BETWEEN 1 FOLLOWING AND 30 FOLLOWING" in sql
    assert "REQUESTED_LAG_28" in sql
    assert "SAMPLED_PRODUCTS" in sql
    assert "LIMIT 10000" not in sql


def test_stockout_query_uses_observed_future_label_without_target_leakage() -> None:
    sql = stockout_supervised_feature_sql(_config()).upper()
    assert "OUT_OF_STOCK" in sql
    assert "TARGET_STOCKOUT_7D" in sql
    assert "RANGE BETWEEN 1 FOLLOWING AND 7 FOLLOWING" in sql
    assert "INVENTORY__STOCK_MOVEMENT" in sql
    assert "BALANCE_AFTER_UNITS" in sql
    assert "RANGE BETWEEN 28 PRECEDING AND 1 PRECEDING" in sql
    assert "CUMULATIVE_DAYS" in sql
    assert "SAMPLED_PAIRS" in sql
    assert "LIMIT 10000" not in sql


def test_reorder_query_has_no_formula_target_leakage() -> None:
    sql = inventory_policy_feature_sql(_config()).upper()
    assert "TARGET_REORDER_UNITS" not in sql
    assert "TARGET_STOCK_UNITS" not in sql
    assert "PROCUREMENT__PURCHASE_ORDER" in sql
    assert "SUPPLIER_RELIABILITY" in sql
    assert "INBOUND_UNITS" in sql


def test_expiry_query_uses_dataset_as_of_date_not_wall_clock() -> None:
    sql = expiry_feature_sql(_config()).upper()
    assert "CURRENT_DATE" not in sql
    assert "MAX(BUSINESS_DATE) AS AS_OF_DATE" in sql
    assert "TARGET_EXPIRY_RISK" not in sql
    assert "EXPIRY_DATE" in sql
    assert "EXPIRY_BUCKET" in sql
    assert "BUCKET_RANK" in sql


def test_stockout_fallback_score_is_monotonic() -> None:
    stressed = stockout_risk_score(
        available_units=2,
        avg_daily_requested_units=12,
        demand_stddev_units=4,
        supplier_lead_time_days=5,
        supplier_reliability=0.80,
        inbound_units=0,
    )
    protected = stockout_risk_score(
        available_units=150,
        avg_daily_requested_units=12,
        demand_stddev_units=4,
        supplier_lead_time_days=5,
        supplier_reliability=0.99,
        inbound_units=50,
    )
    assert 0 <= protected < stressed <= 1
    assert stressed > 0.80
    assert protected < 0.20


def test_reorder_policy_is_nonnegative_and_supply_monotonic() -> None:
    low_supply = reorder_recommendation_units(
        available_units=2,
        avg_daily_requested_units=10,
        demand_stddev_units=3,
        supplier_lead_time_days=4,
        supplier_reliability=0.90,
        inbound_units=0,
    )
    high_supply = reorder_recommendation_units(
        available_units=250,
        avg_daily_requested_units=10,
        demand_stddev_units=3,
        supplier_lead_time_days=4,
        supplier_reliability=0.90,
        inbound_units=0,
    )
    assert low_supply > 0
    assert high_supply == 0
    assert low_supply > high_supply


def test_expiry_probability_behaves_like_sell_through_probability() -> None:
    risky = expiry_risk_score(
        days_to_expiry=20,
        quantity_on_hand=100,
        avg_daily_units_sold=0.5,
        demand_stddev_units=0.8,
    )
    safe = expiry_risk_score(
        days_to_expiry=365,
        quantity_on_hand=20,
        avg_daily_units_sold=5,
        demand_stddev_units=2,
    )
    assert 0 <= safe < risky <= 1
    assert risky > 0.80
    assert safe < 0.20
    assert (
        expiry_risk_score(
            days_to_expiry=-1,
            quantity_on_hand=10,
            avg_daily_units_sold=5,
            demand_stddev_units=1,
        )
        == 1
    )


def test_stage7k_storage_guard() -> None:
    config = _config()
    assert storage_status(7.926, config) == "SAFE"
    assert storage_status(8.2, config) == "WARN"
    assert storage_status(8.5, config) == "STOP"


def test_stage7k_contract_requires_scientific_validation_and_zero_cloud_mutation() -> None:
    contract = stage7k_contract()
    assert contract["production_hardening"] == "v0.34.2"
    assert contract["bigquery"]["writes"] is False
    assert contract["quality"]["strict_champion_gate"] is True
    assert contract["quality"]["target_leakage_allowed"] is False
    assert contract["mlflow"]["champion_alias"] == "ONLY_AFTER_QUALITY_PASS"
    assert contract["cloud_ready"]["deployment_enabled"] is False


def test_cloud_ready_plan_is_zero_cost_by_default() -> None:
    plan = cloud_ready_plan("example-project")
    assert plan["cloud_mutation"] is False
    assert plan["billing_enabled_by_this_stage"] is False
    assert plan["paid_resources_created"] is False
    assert plan["terraform_default_enable_billable_resources"] is False
    assert {item["runtime"] for item in plan["targets"]} == {
        "Vertex AI custom prediction",
        "Cloud Run",
    }


def test_stage7k_pins_current_mlflow_release() -> None:
    requirements = Path("infra/docker/stage7k/requirements.txt").read_text(encoding="utf-8")
    assert "mlflow==3.15.2" in requirements


def test_checkpoint_7k_is_registered() -> None:
    assert checkpoint_command("7k")[1:] == ["scripts/run_stage7k.py"]


def test_mlflow_docker_dns_host_is_explicitly_allowed() -> None:
    compose = Path("infra/docker/docker-compose.stage7k.yml").read_text(encoding="utf-8")
    assert "--allowed-hosts" in compose
    assert "mlflow:5000" in compose
    assert "localhost:*" in compose
    assert '"*"' not in compose
    assert "--cors-allowed-origins" in compose


def test_history_coverage_and_seed_queries_are_read_only() -> None:
    config = _config()
    for sql in (
        history_coverage_sql(config),
        demand_calibration_seed_sql(config),
        stockout_calibration_seed_sql(config),
    ):
        upper = sql.upper()
        assert upper.startswith("WITH ")
        assert "INSERT INTO" not in upper
        assert "CREATE TABLE" not in upper
        assert "MERGE " not in upper


def test_offline_demand_history_has_true_28d_lags_and_30d_targets() -> None:
    seed = pd.DataFrame(
        [
            {
                "product_id": f"p{index}",
                "retail_price_egp": 50.0 + index,
                "avg_requested_units": 12.0 + index,
                "std_requested_units": 5.0,
                "avg_selling_branches": 20.0,
                "avg_transactions_per_requested_unit": 0.6,
                "lost_rate": 0.03,
            }
            for index in range(40)
        ]
    )
    frame = build_demand_history(
        seed, end_date=date(2026, 8, 22), days=120, row_budget=10_000
    )
    assert len(frame) >= 1_000
    assert frame["requested_lag_28"].notna().all()
    assert frame["target_demand_30d"].notna().all()
    assert frame["business_date"].nunique() >= 60


def test_offline_stockout_history_has_future_labels_and_positive_events() -> None:
    seed = pd.DataFrame(
        [
            {
                "branch_id": f"b{index % 8}",
                "product_id": f"p{index}",
                "avg_requested_units": 4.0 + (index % 5),
                "std_requested_units": 3.0,
                "active_day_rate": 0.75,
                "available_units": 8.0,
                "supplier_lead_time_days": 4.0,
                "supplier_reliability": 0.82,
                "lost_rate": 0.05,
                "stockout_rate": 0.04,
            }
            for index in range(50)
        ]
    )
    frame = build_stockout_history(
        seed, end_date=date(2026, 8, 22), days=120, row_budget=10_000
    )
    assert len(frame) >= 1_000
    assert frame["requested_avg_28"].notna().all()
    assert frame["target_stockout_7d"].notna().all()
    assert frame["future_demand_21d"].notna().all()
    assert frame["target_stockout_7d"].sum() > 0
    assert OFFLINE_HISTORY_PROVENANCE == "SYNTHETIC_CALIBRATED_OFFLINE_BACKFILL"


def test_offline_history_sanitizes_non_finite_calibration_values() -> None:
    demand_seed = pd.DataFrame(
        [
            {
                "product_id": "p-nan",
                "avg_requested_units": 5.0,
                "std_requested_units": float("nan"),
                "retail_price_egp": float("nan"),
                "avg_selling_branches": float("nan"),
                "avg_transactions_per_requested_unit": float("nan"),
                "lost_rate": float("nan"),
            }
        ]
    )
    demand = build_demand_history(
        demand_seed, end_date=date(2026, 8, 22), days=120, row_budget=10_000
    )
    assert not demand.empty
    assert demand.select_dtypes(include="number").notna().all().all()

    stockout_seed = pd.DataFrame(
        [
            {
                "branch_id": "b-nan",
                "product_id": "p-nan",
                "avg_requested_units": 5.0,
                "std_requested_units": float("nan"),
                "active_day_rate": float("nan"),
                "available_units": float("nan"),
                "supplier_lead_time_days": float("nan"),
                "supplier_reliability": float("nan"),
                "lost_rate": float("nan"),
                "stockout_rate": float("nan"),
            }
        ]
    )
    stockout = build_stockout_history(
        stockout_seed, end_date=date(2026, 8, 22), days=120, row_budget=10_000
    )
    assert not stockout.empty
    assert stockout.select_dtypes(include="number").notna().all().all()
    assert (stockout["supplier_lead_time_days"] >= 1).all()
    assert stockout["supplier_reliability"].between(0.55, 0.995).all()


def test_mlflow_skops_serialization_uses_explicit_custom_type_allowlist() -> None:
    train_source = Path("ml/stage7k/train.py").read_text(encoding="utf-8")
    assert "SERIALIZATION_FORMAT_SKOPS" in train_source
    assert "skops_trusted_types=_trusted_skops_types(model)" in train_source
    assert 'code_paths=["/workspace/ml"]' in train_source
    assert "SERIALIZATION_FORMAT_CLOUDPICKLE" not in train_source
    for qualified_type in (
        "ml.stage7k.models.MultiHorizonDemandModel",
        "ml.stage7k.models.CalibratedThresholdClassifier",
        "ml.stage7k.models.ReorderPolicyModel",
        "ml.stage7k.models.ExpiryRiskModel",
    ):
        assert qualified_type in train_source


def test_stockout_offline_simulation_preserves_rare_positive_class() -> None:
    seed = pd.DataFrame(
        [
            {
                "branch_id": f"b{index % 10}",
                "product_id": f"p{index}",
                "avg_requested_units": 2.0 + (index % 5) * 0.4,
                "std_requested_units": 1.5,
                "active_day_rate": 0.50,
                "available_units": 25.0,
                "supplier_lead_time_days": 4.0,
                "supplier_reliability": 0.90,
                "lost_rate": 0.0,
                "stockout_rate": 0.0,
            }
            for index in range(50)
        ]
    )
    frame = build_stockout_history(
        seed, end_date=date(2026, 8, 22), days=160, row_budget=10_000
    )
    prevalence = float(frame["target_stockout_7d"].mean())
    assert 0.002 <= prevalence <= 0.20


def test_stockout_offline_simulation_responds_to_observed_risk_calibration() -> None:
    def _seed(stockout_rate: float, lost_rate: float) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "branch_id": f"b{index % 10}",
                    "product_id": f"p{index}",
                    "avg_requested_units": 2.0 + (index % 5) * 0.4,
                    "std_requested_units": 1.5,
                    "active_day_rate": 0.50,
                    "available_units": 25.0,
                    "supplier_lead_time_days": 4.0,
                    "supplier_reliability": 0.90,
                    "lost_rate": lost_rate,
                    "stockout_rate": stockout_rate,
                }
                for index in range(50)
            ]
        )

    low_risk = build_stockout_history(
        _seed(0.0, 0.0), end_date=date(2026, 8, 22), days=160, row_budget=10_000
    )
    elevated_risk = build_stockout_history(
        _seed(0.08, 0.05), end_date=date(2026, 8, 22), days=160, row_budget=10_000
    )
    assert float(elevated_risk["target_stockout_7d"].mean()) > float(
        low_risk["target_stockout_7d"].mean()
    )


def test_stockout_rare_event_sufficiency_constants_are_statistically_practical() -> None:
    source = (Path(__file__).parents[1] / "ml" / "stage7k" / "train.py").read_text()

    assert "MIN_TRAIN_POSITIVES = 100" in source
    assert "MIN_VALIDATION_POSITIVES = 30" in source
    assert "MIN_TEST_POSITIVES = 40" in source
    assert "MIN_TOTAL_POSITIVES = 200" in source
    assert "Stockout rare-event sufficiency: PASS" in source


def test_stage7k_v0342_runtime_version_is_consistent() -> None:
    assert STAGE7K_VERSION == "0.34.2"
    assert 'version = "0.34.2"' in Path("pyproject.toml").read_text(encoding="utf-8")
    runtime_files = (
        "ml/stage7k/train.py",
        "ml/stage7k/serve.py",
        "ml/stage7k/cloud_serve.py",
        "ml/stage7k/vertex_serve.py",
        "scripts/run_stage7k.py",
        "src/pharmstock/ml/stage7k.py",
    )
    for name in runtime_files:
        text = Path(name).read_text(encoding="utf-8")
        assert "v0.33.3" not in text
        assert "v0.33.8" not in text
        assert 'version="0.33.0"' not in text


def test_demand_runtime_has_validation_only_hybrid_baseline_fallback() -> None:
    train_source = Path("ml/stage7k/train.py").read_text(encoding="utf-8")
    model_source = Path("ml/stage7k/models.py").read_text(encoding="utf-8")
    assert "_select_demand_blend" in train_source
    assert "baseline_safety_fallback" in train_source
    assert "ml_is_never_forced_when_baseline_is_stronger" in train_source
    assert "blend_weights" in model_source
    assert "baseline_names" in model_source
    assert "Backward compatibility for pre-v0.34.0 registered artifacts" in model_source


def test_stockout_runtime_uses_rare_event_operating_threshold_not_point_five() -> None:
    source = Path("ml/stage7k/train.py").read_text(encoding="utf-8")
    assert "precision_recall_curve" in source
    assert "validation_top10pct_fallback" in source
    assert "precision_lift_vs_prevalence" in source
    assert "pr_auc_lift_vs_prevalence" in source
    assert "_rare_event_requirements" in source
    assert "np.linspace(0.05, 0.80, 76)" not in source
    assert "ap_floor = max(0.03" not in source


def test_stage7k_suppresses_only_harmless_runtime_warnings_without_cleanup() -> None:
    launcher = Path("scripts/run_stage7k.py").read_text(encoding="utf-8")
    compose = Path("infra/docker/docker-compose.stage7k.yml").read_text(encoding="utf-8")
    assert 'COMPOSE_IGNORE_ORPHANS", "true"' in launcher
    assert "--remove-orphans" not in launcher
    assert "GIT_PYTHON_REFRESH: quiet" in compose


def test_stockout_acceptance_is_relative_to_event_prevalence() -> None:
    source = Path("ml/stage7k/train.py").read_text(encoding="utf-8")
    for token in (
        '"pr_auc_lift": 10.0',
        '"pr_auc_lift": 5.0',
        '"pr_auc_lift": 2.0',
        '"precision_lift": 5.0',
        '"top10_recall": 0.50',
    ):
        assert token in source


def test_cloud_bundle_preserves_python_package_path_for_joblib_models() -> None:
    source = Path("scripts/export_stage7k_cloud_bundle.py").read_text(encoding="utf-8")
    assert 'package_dir = OUTPUT / "ml" / "stage7k"' in source
    assert '"COPY ml /app/ml\\nENV PYTHONPATH=/app\\n' in source
    assert 'ml.stage7k.vertex_serve:app' in source
    assert 'ml.stage7k.cloud_serve:app' in source


def test_temporal_validation_uses_target_horizon_embargoes() -> None:
    source = Path("ml/stage7k/train.py").read_text(encoding="utf-8")
    assert "embargo_days=max(DEMAND_HORIZONS)" in source
    assert "embargo_days=7" in source
    assert "safe_train_end = max(1, train_end - int(horizon))" in source
    assert "purged temporal train/validation/test split" in source


def test_synthetic_backfill_caps_demand_ml_correction_for_tail_risk() -> None:
    source = Path("ml/stage7k/train.py").read_text(encoding="utf-8")
    assert "SYNTHETIC_BACKFILL_MAX_BLEND_WEIGHT = 0.15" in source
    assert "max_weight=max_blend_weight" in source
    assert "synthetic_backfill_tail_risk_guard" in source
    assert "Demand ML blend cap:" in source
