"""Zero-cost cloud deployment blueprint for Stage 7K.

This module never calls Google Cloud APIs. It only describes the production
landing zone that can be applied later if billing is explicitly enabled.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class CloudTarget:
    component: str
    runtime: str
    reason: str
    billable_when_deployed: bool


CLOUD_TARGETS = (
    CloudTarget(
        component="demand_forecast",
        runtime="Vertex AI custom prediction",
        reason="managed predictive-model endpoint, versioning and monitoring",
        billable_when_deployed=True,
    ),
    CloudTarget(
        component="stockout_risk",
        runtime="Vertex AI custom prediction",
        reason="managed calibrated classifier endpoint and drift monitoring",
        billable_when_deployed=True,
    ),
    CloudTarget(
        component="reorder_recommendation",
        runtime="Cloud Run",
        reason="deterministic prescriptive decision engine",
        billable_when_deployed=True,
    ),
    CloudTarget(
        component="expiry_slow_moving_risk",
        runtime="Cloud Run",
        reason="probabilistic policy engine with transparent business logic",
        billable_when_deployed=True,
    ),
)


def cloud_ready_plan(project_id: str, region: str = "europe-west1") -> dict[str, object]:
    return {
        "stage": "7K.4",
        "mode": "BLUEPRINT_ONLY",
        "project_id": project_id,
        "region": region,
        "cloud_mutation": False,
        "billing_enabled_by_this_stage": False,
        "paid_resources_created": False,
        "terraform_default_enable_billable_resources": False,
        "targets": [asdict(item) for item in CLOUD_TARGETS],
        "registry": {
            "planned": "Artifact Registry",
            "image_repository": "pharmstock-ml",
            "runtime_image_strategy": "immutable digest + semantic tag",
        },
        "model_lifecycle": {
            "local_source_of_truth": "MLflow candidate/champion/previous_champion aliases",
            "cloud_promotion": "manual gated promotion after scientific validation",
            "rollback": "previous immutable model/image version",
        },
        "security": {
            "public_invoker": False,
            "service_accounts": "least privilege",
            "secrets": "Secret Manager reference only; no secrets in image or Terraform",
        },
        "monitoring": {
            "predictive_models": "Vertex model monitoring/drift plan",
            "decision_engines": "Cloud Run logs, latency/error metrics, input distribution drift",
        },
        "cost_guard": {
            "rule": "NO APPLY / NO PUSH / NO DEPLOY unless explicitly approved later",
            "current_stage_action": "render and validate local artifacts only",
        },
    }
