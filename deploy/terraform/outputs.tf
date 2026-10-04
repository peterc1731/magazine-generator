output "web_url" {
  description = "Public URL of the web service (OPDS at /opds/, UI at /ui/)."
  value       = google_cloud_run_v2_service.web.uri
}

output "image_repository" {
  description = "Artifact Registry path images are pushed to."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "web_service_name" {
  value = google_cloud_run_v2_service.web.name
}

output "pipeline_job_name" {
  value = google_cloud_run_v2_job.pipeline.name
}

output "migrate_job_name" {
  value = google_cloud_run_v2_job.migrate.name
}

output "env_secret_name" {
  description = "Secret Manager secret holding the production .env."
  value       = google_secret_manager_secret.env.secret_id
}

output "github_workload_identity_provider" {
  description = "Set as the GCP_WORKLOAD_IDENTITY_PROVIDER repository variable."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "github_deployer_service_account" {
  description = "Set as the GCP_DEPLOYER_SERVICE_ACCOUNT repository variable."
  value       = google_service_account.deployer.email
}
