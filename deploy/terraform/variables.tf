variable "project_id" {
  description = "GCP project to deploy into."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, Cloud Scheduler, Artifact Registry and the storage bucket. us-central1/us-east1/us-west1 keep the bucket inside Cloud Storage's free tier."
  type        = string
  default     = "us-central1"
}

variable "github_repo" {
  description = "owner/repo allowed to deploy via Workload Identity Federation."
  type        = string
  default     = "peterc1731/magazine-generator"
}

variable "schedule" {
  description = "Cron expression for the pipeline run (Cloud Scheduler owns the schedule on this deployment, not the cron setting in the web UI)."
  type        = string
  default     = "0 8 * * MON"
}

variable "time_zone" {
  description = "IANA time zone the schedule is interpreted in."
  type        = string
  default     = "Etc/UTC"
}
