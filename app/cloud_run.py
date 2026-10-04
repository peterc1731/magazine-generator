import google.auth
import google.auth.transport.requests
import httpx

RUN_API_BASE = "https://run.googleapis.com/v2"
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


def start_pipeline_job(job_name: str, client: httpx.Client | None = None) -> None:
    """Starts an execution of the Cloud Run Job `job_name`
    (projects/P/locations/R/jobs/J) and returns without waiting for it.

    Authenticates as the service's own runtime service account via
    Application Default Credentials (the metadata server on Cloud Run),
    which deploy/terraform grants run.invoker on the job. google-auth only
    consults the metadata server when `requests` is installed — hence the
    google-auth[requests] dependency.
    """
    credentials, _ = google.auth.default(scopes=SCOPES)
    credentials.refresh(google.auth.transport.requests.Request())

    http = client or httpx.Client(timeout=30.0)
    response = http.post(
        f"{RUN_API_BASE}/{job_name}:run",
        headers={"Authorization": f"Bearer {credentials.token}"},
        json={},
    )
    response.raise_for_status()
