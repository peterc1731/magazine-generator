from unittest.mock import MagicMock, patch

import httpx
import respx

from app.cloud_run import RUN_API_BASE, start_pipeline_job

JOB_NAME = "projects/my-project/locations/us-central1/jobs/magazine-pipeline"


@respx.mock
@patch("app.cloud_run.google.auth.default")
def test_start_pipeline_job_posts_run_with_bearer_token(mock_default: MagicMock) -> None:
    credentials = MagicMock(token="access-token")
    mock_default.return_value = (credentials, "my-project")
    route = respx.post(f"{RUN_API_BASE}/{JOB_NAME}:run").mock(
        return_value=httpx.Response(200, json={"name": "operations/123"})
    )

    start_pipeline_job(JOB_NAME)

    assert credentials.refresh.called
    assert route.calls[0].request.headers["Authorization"] == "Bearer access-token"
