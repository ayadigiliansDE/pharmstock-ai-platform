locals {
  enabled_count = var.enable_billable_resources ? 1 : 0
  labels = {
    platform = "pharmstock"
    stage    = "7k4"
    managed  = "terraform"
  }
}

# API activation is also cloud mutation, so even this is disabled by default.
resource "google_project_service" "required" {
  for_each = var.enable_billable_resources ? toset([
    "artifactregistry.googleapis.com",
    "run.googleapis.com",
    "aiplatform.googleapis.com",
    "secretmanager.googleapis.com",
  ]) : toset([])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "ml" {
  count = var.enable_billable_resources ? 1 : 0

  project       = var.project_id
  location      = var.region
  repository_id = var.artifact_repository_id
  description   = "Immutable PharmStock ML and decision-engine images"
  format        = "DOCKER"
  labels        = local.labels

  depends_on = [google_project_service.required]
}

resource "google_service_account" "decision_runtime" {
  count = var.enable_billable_resources ? 1 : 0

  project      = var.project_id
  account_id   = "pharmstock-decision-runtime"
  display_name = "PharmStock decision runtime"
}

resource "google_service_account" "vertex_runtime" {
  count = var.enable_billable_resources ? 1 : 0

  project      = var.project_id
  account_id   = "pharmstock-vertex-runtime"
  display_name = "PharmStock Vertex prediction runtime"
}

resource "google_project_iam_member" "vertex_runtime_user" {
  count = var.enable_billable_resources ? 1 : 0

  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.vertex_runtime[0].email}"
}

resource "google_cloud_run_v2_service" "decision_api" {
  count = var.enable_billable_resources ? 1 : 0

  project  = var.project_id
  name     = "pharmstock-decision-api"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"
  labels   = local.labels

  template {
    service_account = google_service_account.decision_runtime[0].email

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = var.decision_api_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }

  depends_on = [
    google_project_service.required,
    google_artifact_registry_repository.ml,
  ]
}

# Endpoint shell only. Actual model upload/deploy is intentionally outside
# Terraform in this zero-cost stage so model promotion remains an explicit,
# audited action after scientific acceptance.
resource "google_vertex_ai_endpoint" "predictive" {
  count = var.enable_billable_resources ? 1 : 0

  project      = var.project_id
  display_name = var.vertex_endpoint_display_name
  name         = "pharmstock-predictive"
  location     = var.region
  labels       = local.labels

  depends_on = [google_project_service.required]
}
