terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Bucket is supplied at init time (`-backend-config=bucket=...`) — it's
  # created by deploy/bootstrap.sh, before Terraform can run at all.
  backend "gcs" {
    prefix = "magazine-generator"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
