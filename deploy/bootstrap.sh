#!/usr/bin/env bash
# One-time setup for the Cloud Run deployment, run from your own machine
# with project-owner credentials. After this, every push to main deploys
# via .github/workflows/deploy.yml — this script isn't needed again.
#
# Prerequisites: gcloud and terraform installed, an existing GCP project
# with billing linked, and `gcloud auth login` +
# `gcloud auth application-default login` done.
#
# Usage: deploy/bootstrap.sh <project-id> [region]
set -euo pipefail

PROJECT_ID="${1:?usage: deploy/bootstrap.sh <project-id> [region]}"
REGION="${2:-us-central1}"
STATE_BUCKET="${PROJECT_ID}-tfstate"
TF_DIR="$(cd "$(dirname "$0")/terraform" && pwd)"

echo "==> Enabling the APIs Terraform needs before it can manage the rest"
gcloud services enable \
  cloudresourcemanager.googleapis.com \
  serviceusage.googleapis.com \
  iam.googleapis.com \
  storage.googleapis.com \
  --project "$PROJECT_ID"

echo "==> Creating Terraform state bucket gs://${STATE_BUCKET}"
if ! gcloud storage buckets describe "gs://${STATE_BUCKET}" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${STATE_BUCKET}" \
    --project "$PROJECT_ID" \
    --location "$REGION" \
    --uniform-bucket-level-access \
    --public-access-prevention
fi
gcloud storage buckets update "gs://${STATE_BUCKET}" --versioning

echo "==> Applying Terraform"
terraform -chdir="$TF_DIR" init -input=false -backend-config="bucket=${STATE_BUCKET}"
terraform -chdir="$TF_DIR" apply -input=false \
  -var "project_id=${PROJECT_ID}" \
  -var "region=${REGION}"

cat <<NEXT

Done. Next steps (see README.md "Deploying to Google Cloud Run"):

1. Upload the production .env to Secret Manager:
     gcloud secrets versions add $(terraform -chdir="$TF_DIR" output -raw env_secret_name) \\
       --project ${PROJECT_ID} --data-file=.env.production

2. Set these GitHub repository variables (Settings → Secrets and variables
   → Actions → Variables):
     GCP_PROJECT_ID                  = ${PROJECT_ID}
     GCP_REGION                      = ${REGION}
     TF_STATE_BUCKET                 = ${STATE_BUCKET}
     GCP_WORKLOAD_IDENTITY_PROVIDER  = $(terraform -chdir="$TF_DIR" output -raw github_workload_identity_provider)
     GCP_DEPLOYER_SERVICE_ACCOUNT    = $(terraform -chdir="$TF_DIR" output -raw github_deployer_service_account)

3. Push to main (or run the Deploy workflow manually) to build and roll
   out the app. It will be served at:
     $(terraform -chdir="$TF_DIR" output -raw web_url)
NEXT
