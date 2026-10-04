locals {
  # Cloud Run needs *some* image to create the service and jobs with. The
  # deploy workflow replaces it with the real one on every push, and the
  # resources below ignore image changes so Terraform doesn't revert it.
  placeholder_image = "us-docker.pkg.dev/cloudrun/container/hello"

  storage_mount = "/mnt/storage"
  secrets_mount = "/secrets"

  # Plain (non-secret) config shared by the web service and both jobs.
  # Everything secret comes from the .env stored in Secret Manager, read
  # via ENV_FILE; real env vars like these take precedence over it.
  common_env = {
    ENV_FILE                = "${local.secrets_mount}/env"
    DATA_DIR                = "${local.storage_mount}/data"
    ISSUES_DIR              = "${local.storage_mount}/output"
    RUN_MIGRATIONS_ON_START = "false"
  }

  services = [
    "artifactregistry.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "cloudscheduler.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "serviceusage.googleapis.com",
    "storage.googleapis.com",
    "sts.googleapis.com",
  ]
}

resource "google_project_service" "enabled" {
  for_each           = toset(local.services)
  service            = each.value
  disable_on_destroy = false
}

# --- Images ------------------------------------------------------------------

resource "google_artifact_registry_repository" "images" {
  repository_id = "magazine"
  location      = var.region
  format        = "DOCKER"

  cleanup_policy_dry_run = false
  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 5
    }
  }
  cleanup_policies {
    id     = "delete-old"
    action = "DELETE"
    condition {
      older_than = "604800s" # 7 days — KEEP above wins for the newest 5
    }
  }

  depends_on = [google_project_service.enabled]
}

# --- Storage (cleaned article HTML, covers, epubs) ---------------------------

resource "google_storage_bucket" "storage" {
  name                        = "${var.project_id}-magazine"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  depends_on = [google_project_service.enabled]
}

# --- Secrets -----------------------------------------------------------------

# The whole production .env, as one secret — same shape as the Compose
# deployment's .env file. Add the real contents with:
#   gcloud secrets versions add magazine-env --data-file=.env.production
resource "google_secret_manager_secret" "env" {
  secret_id = "magazine-env"
  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}

# Cloud Run refuses to start a revision whose secret has no versions, so
# seed an empty one. Settings fall back to defaults until the real .env
# version is added on top (Cloud Run reads "latest").
resource "google_secret_manager_secret_version" "env_placeholder" {
  secret      = google_secret_manager_secret.env.id
  secret_data = "# Placeholder - add the real .env as a new version of this secret.\n"
}

# --- Runtime identity --------------------------------------------------------

resource "google_service_account" "runtime" {
  account_id   = "magazine-runtime"
  display_name = "Magazine generator (web + jobs runtime)"
}

resource "google_secret_manager_secret_iam_member" "runtime_env" {
  secret_id = google_secret_manager_secret.env.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_storage_bucket_iam_member" "runtime_storage" {
  bucket = google_storage_bucket.storage.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

# --- Cloud Run: web (OPDS + UI) ----------------------------------------------

resource "google_cloud_run_v2_service" "web" {
  name                = "magazine-web"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account       = google_service_account.runtime.email
    execution_environment = "EXECUTION_ENVIRONMENT_GEN2" # needed for the GCS volume

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = local.placeholder_image

      ports {
        container_port = 8000
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      dynamic "env" {
        for_each = merge(local.common_env, {
          PIPELINE_JOB_NAME = google_cloud_run_v2_job.pipeline.id
        })
        content {
          name  = env.key
          value = env.value
        }
      }

      volume_mounts {
        name       = "storage"
        mount_path = local.storage_mount
      }
      volume_mounts {
        name       = "env"
        mount_path = local.secrets_mount
      }
    }

    volumes {
      name = "storage"
      gcs {
        bucket    = google_storage_bucket.storage.name
        read_only = false
      }
    }
    volumes {
      name = "env"
      secret {
        secret = google_secret_manager_secret.env.secret_id
        items {
          version = "latest"
          path    = "env"
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  depends_on = [
    google_secret_manager_secret_version.env_placeholder,
    google_secret_manager_secret_iam_member.runtime_env,
    google_storage_bucket_iam_member.runtime_storage,
  ]
}

# Public at the Cloud Run layer; the app's own basic auth
# (OPDS_BASIC_AUTH_USER/PASSWORD) is what gates access, since e-reader OPDS
# clients can't do Google sign-in.
resource "google_cloud_run_v2_service_iam_member" "web_public" {
  name     = google_cloud_run_v2_service.web.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- Cloud Run: jobs ---------------------------------------------------------

resource "google_cloud_run_v2_job" "pipeline" {
  name                = "magazine-pipeline"
  location            = var.region
  deletion_protection = false

  template {
    task_count = 1

    template {
      service_account       = google_service_account.runtime.email
      execution_environment = "EXECUTION_ENVIRONMENT_GEN2"
      timeout               = "3600s"
      # A retry would re-run classification (Anthropic spend) and could
      # build a duplicate issue; failures notify via ntfy instead.
      max_retries = 0

      containers {
        image = local.placeholder_image
        args  = ["python", "scripts/run_now.py"]

        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }

        dynamic "env" {
          for_each = local.common_env
          content {
            name  = env.key
            value = env.value
          }
        }

        volume_mounts {
          name       = "storage"
          mount_path = local.storage_mount
        }
        volume_mounts {
          name       = "env"
          mount_path = local.secrets_mount
        }
      }

      volumes {
        name = "storage"
        gcs {
          bucket    = google_storage_bucket.storage.name
          read_only = false
        }
      }
      volumes {
        name = "env"
        secret {
          secret = google_secret_manager_secret.env.secret_id
          items {
            version = "latest"
            path    = "env"
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  depends_on = [
    google_secret_manager_secret_version.env_placeholder,
    google_secret_manager_secret_iam_member.runtime_env,
    google_storage_bucket_iam_member.runtime_storage,
  ]
}

# Runs `alembic upgrade head`; the deploy workflow executes it after pushing
# a new image and before rolling that image out to the service and pipeline.
resource "google_cloud_run_v2_job" "migrate" {
  name                = "magazine-migrate"
  location            = var.region
  deletion_protection = false

  template {
    task_count = 1

    template {
      service_account = google_service_account.runtime.email
      timeout         = "600s"
      max_retries     = 0

      containers {
        image = local.placeholder_image
        args  = ["alembic", "upgrade", "head"]

        dynamic "env" {
          for_each = local.common_env
          content {
            name  = env.key
            value = env.value
          }
        }

        volume_mounts {
          name       = "env"
          mount_path = local.secrets_mount
        }
      }

      volumes {
        name = "env"
        secret {
          secret = google_secret_manager_secret.env.secret_id
          items {
            version = "latest"
            path    = "env"
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  depends_on = [
    google_secret_manager_secret_version.env_placeholder,
    google_secret_manager_secret_iam_member.runtime_env,
  ]
}

# The web service starts the pipeline job for "Run now" in the UI.
resource "google_cloud_run_v2_job_iam_member" "runtime_runs_pipeline" {
  name     = google_cloud_run_v2_job.pipeline.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.runtime.email}"
}

# --- Schedule ----------------------------------------------------------------

resource "google_service_account" "scheduler" {
  account_id   = "magazine-scheduler"
  display_name = "Magazine generator (Cloud Scheduler trigger)"
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_runs_pipeline" {
  name     = google_cloud_run_v2_job.pipeline.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

resource "google_cloud_scheduler_job" "pipeline" {
  name        = "magazine-pipeline-schedule"
  region      = var.region
  schedule    = var.schedule
  time_zone   = var.time_zone
  description = "Starts the weekly magazine pipeline run."

  retry_config {
    retry_count = 0
  }

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/${google_cloud_run_v2_job.pipeline.id}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [google_cloud_run_v2_job_iam_member.scheduler_runs_pipeline]
}
