output "cost_guard_enabled" {
  value       = !var.enable_billable_resources
  description = "True means Terraform will create zero cloud resources."
}

output "artifact_repository" {
  value       = try(google_artifact_registry_repository.ml[0].name, null)
  description = "Null while the zero-cost guard is active."
}

output "decision_api_uri" {
  value       = try(google_cloud_run_v2_service.decision_api[0].uri, null)
  description = "Null while the zero-cost guard is active."
}

output "vertex_endpoint_id" {
  value       = try(google_vertex_ai_endpoint.predictive[0].id, null)
  description = "Null while the zero-cost guard is active."
}
