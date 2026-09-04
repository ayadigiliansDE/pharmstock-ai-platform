variable "project_id" {
  type        = string
  description = "Existing GCP project. No project is created by this blueprint."
}

variable "region" {
  type        = string
  description = "Target runtime region if deployment is explicitly enabled later."
  default     = "europe-west1"
}

variable "enable_billable_resources" {
  type        = bool
  description = "Hard cost guard. MUST remain false for the zero-cost portfolio build."
  default     = false
}

variable "artifact_repository_id" {
  type    = string
  default = "pharmstock-ml"
}

variable "decision_api_image" {
  type        = string
  description = "Immutable Artifact Registry image URI for the Cloud Run decision API."
  default     = "europe-west1-docker.pkg.dev/REPLACE_PROJECT/pharmstock-ml/decision-api:REPLACE_DIGEST"
}

variable "vertex_endpoint_display_name" {
  type    = string
  default = "pharmstock-predictive-models"
}
