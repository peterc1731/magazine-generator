from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings, get_settings
from app.db import get_db
from app.main import app
from app.models import Base, JobRun, JobStatus, Source, SourceType
from connectors.base import FetchResult, RawItem


@pytest.fixture
def session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path}/web-test.db")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_index_redirects_to_sources(client: TestClient) -> None:
    response = client.get("/ui/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/ui/sources"


def test_ui_requires_auth_when_configured(session_factory) -> None:
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, opds_basic_auth_user="alice", opds_basic_auth_password="secret"
    )
    try:
        test_client = TestClient(app)
        assert test_client.get("/ui/sources").status_code == 401
        assert test_client.get("/ui/sources", auth=("alice", "wrong")).status_code == 401
        assert test_client.get("/ui/sources", auth=("alice", "secret")).status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_sources_list_empty(client: TestClient) -> None:
    response = client.get("/ui/sources")

    assert response.status_code == 200
    assert "No sources yet" in response.text


def test_create_guardian_source(client: TestClient, session_factory) -> None:
    response = client.post(
        "/ui/sources",
        data={"name": "The Guardian", "type": "guardian_api", "section": "technology"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    with session_factory() as db:
        source = db.query(Source).one()
        assert source.name == "The Guardian"
        assert source.type == SourceType.GUARDIAN_API
        assert source.config == {"section": "technology"}
        assert source.enabled is True


def test_create_rss_source(client: TestClient, session_factory) -> None:
    client.post(
        "/ui/sources",
        data={"name": "BBC News", "type": "rss", "feed_url": "https://bbc.co.uk/rss"},
    )

    with session_factory() as db:
        source = db.query(Source).one()
        assert source.config == {"feed_url": "https://bbc.co.uk/rss"}


def test_create_web_archive_source_with_fetch_limit(client: TestClient, session_factory) -> None:
    client.post(
        "/ui/sources",
        data={
            "name": "Dense Discovery",
            "type": "web_archive",
            "archive_url": "https://example.com/issues/",
            "link_selector": "a.issue",
            "initial_fetch_limit": "3",
        },
    )

    with session_factory() as db:
        source = db.query(Source).one()
        assert source.config == {
            "archive_url": "https://example.com/issues/",
            "link_selector": "a.issue",
            "initial_fetch_limit": 3,
        }


def test_create_x_bookmarks_source_has_empty_config(client: TestClient, session_factory) -> None:
    client.post("/ui/sources", data={"name": "X Bookmarks", "type": "x_bookmarks"})

    with session_factory() as db:
        source = db.query(Source).one()
        assert source.config == {}


def test_edit_source_form_prefilled(client: TestClient, session_factory) -> None:
    with session_factory() as db:
        source = Source(name="BBC News", type=SourceType.RSS, config={"feed_url": "https://x.test"})
        db.add(source)
        db.commit()
        db.refresh(source)
        source_id = source.id

    response = client.get(f"/ui/sources/{source_id}/edit")

    assert response.status_code == 200
    assert "https://x.test" in response.text


def test_update_source_changes_config(client: TestClient, session_factory) -> None:
    with session_factory() as db:
        source = Source(name="BBC News", type=SourceType.RSS, config={"feed_url": "https://old"})
        db.add(source)
        db.commit()
        db.refresh(source)
        source_id = source.id

    client.post(
        f"/ui/sources/{source_id}",
        data={"name": "BBC News UK", "type": "rss", "feed_url": "https://new"},
    )

    with session_factory() as db:
        source = db.get(Source, source_id)
        assert source.name == "BBC News UK"
        assert source.config == {"feed_url": "https://new"}


def test_toggle_source_flips_enabled(client: TestClient, session_factory) -> None:
    with session_factory() as db:
        source = Source(name="BBC News", type=SourceType.RSS, config={}, enabled=True)
        db.add(source)
        db.commit()
        db.refresh(source)
        source_id = source.id

    response = client.post(f"/ui/sources/{source_id}/toggle")

    assert response.status_code == 200
    assert "disable" in response.text
    with session_factory() as db:
        assert db.get(Source, source_id).enabled is False


@patch("app.web.build_connector")
def test_test_fetch_shows_found_items(
    mock_build_connector: MagicMock, client: TestClient, session_factory
) -> None:
    with session_factory() as db:
        source = Source(name="BBC News", type=SourceType.RSS, config={})
        db.add(source)
        db.commit()
        db.refresh(source)
        source_id = source.id

    mock_connector = MagicMock()
    mock_connector.fetch_since.return_value = FetchResult(
        items=[
            RawItem(source_item_id="1", title="First story", url="https://x/1", published_at=None)
        ],
        next_cursor="c1",
    )
    mock_build_connector.return_value = mock_connector

    response = client.post(f"/ui/sources/{source_id}/test-fetch")

    assert response.status_code == 200
    assert "Found 1 item(s)" in response.text
    assert "First story" in response.text
    # test-fetch is a preview only — cursor must not move
    with session_factory() as db:
        assert db.get(Source, source_id).last_cursor is None


@patch("app.web.build_connector")
def test_test_fetch_shows_error_on_failure(
    mock_build_connector: MagicMock, client: TestClient, session_factory
) -> None:
    with session_factory() as db:
        source = Source(name="BBC News", type=SourceType.RSS, config={})
        db.add(source)
        db.commit()
        db.refresh(source)
        source_id = source.id

    mock_connector = MagicMock()
    mock_connector.fetch_since.side_effect = RuntimeError("connection refused")
    mock_build_connector.return_value = mock_connector

    response = client.post(f"/ui/sources/{source_id}/test-fetch")

    assert response.status_code == 200
    assert "Failed" in response.text
    assert "connection refused" in response.text


@patch("app.web.build_connector")
def test_test_fetch_escapes_html_in_titles(
    mock_build_connector: MagicMock, client: TestClient, session_factory
) -> None:
    """Article titles come from external, untrusted sources (RSS/scraped
    pages) — a malicious feed title must not inject markup into the page."""
    with session_factory() as db:
        source = Source(name="BBC News", type=SourceType.RSS, config={})
        db.add(source)
        db.commit()
        db.refresh(source)
        source_id = source.id

    mock_connector = MagicMock()
    mock_connector.fetch_since.return_value = FetchResult(
        items=[
            RawItem(
                source_item_id="1",
                title="<script>alert(1)</script>",
                url="https://x/1",
                published_at=None,
            )
        ],
        next_cursor="c1",
    )
    mock_build_connector.return_value = mock_connector

    response = client.post(f"/ui/sources/{source_id}/test-fetch")

    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text


def test_create_numbered_web_archive_source(client: TestClient, session_factory) -> None:
    response = client.post(
        "/ui/sources",
        data={
            "name": "Dense Discovery",
            "type": "web_archive",
            "issue_url_template": "https://www.densediscovery.com/archive/{number}/",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with session_factory() as db:
        source = db.query(Source).filter_by(name="Dense Discovery").one()
        assert source.config["issue_url_template"] == (
            "https://www.densediscovery.com/archive/{number}/"
        )


def test_issue_url_template_must_contain_number_placeholder(client: TestClient) -> None:
    response = client.post(
        "/ui/sources",
        data={
            "name": "Dense Discovery",
            "type": "web_archive",
            "issue_url_template": "https://www.densediscovery.com/archive/",
        },
    )

    assert response.status_code == 400


def test_settings_defaults(client: TestClient) -> None:
    response = client.get("/ui/settings")

    assert response.status_code == 200
    assert "0 8 * * MON" in response.text


def test_settings_roundtrip(client: TestClient, session_factory) -> None:
    response = client.post(
        "/ui/settings",
        data={
            "interest_profile": "AI and cycling",
            "relevance_threshold": "7.5",
            "cron_expression": "0 6 * * *",
        },
    )

    assert response.status_code == 200
    assert "Saved" in response.text
    from pipeline import settings_store

    with session_factory() as db:
        assert settings_store.get_interest_profile(db) == "AI and cycling"
        assert settings_store.get_relevance_threshold(db) == 7.5
        assert settings_store.get_cron_expression(db) == "0 6 * * *"


def test_runs_list_empty(client: TestClient) -> None:
    response = client.get("/ui/runs")

    assert response.status_code == 200
    assert "No runs yet" in response.text


def test_runs_list_shows_run(client: TestClient, session_factory) -> None:
    with session_factory() as db:
        db.add(
            JobRun(
                status=JobStatus.SUCCESS,
                articles_found=5,
                articles_included=2,
                articles_excluded=3,
            )
        )
        db.commit()

    response = client.get("/ui/runs")

    assert "badge-success" in response.text
    assert ">5<" in response.text or "5" in response.text


@patch("app.web.execute_run")
def test_run_now_triggers_execute_run_and_redirects(
    mock_execute_run: MagicMock, client: TestClient
) -> None:
    response = client.post("/ui/runs/run-now", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/ui/runs"
    assert mock_execute_run.called


@pytest.fixture
def cloud_run_client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, pipeline_job_name="projects/p/locations/r/jobs/pipeline"
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


@patch("app.web.execute_run")
@patch("app.web.start_pipeline_job")
def test_run_now_starts_cloud_run_job_when_configured(
    mock_start_job: MagicMock, mock_execute_run: MagicMock, cloud_run_client: TestClient
) -> None:
    response = cloud_run_client.post("/ui/runs/run-now", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/ui/runs?started=true"
    mock_start_job.assert_called_once_with("projects/p/locations/r/jobs/pipeline")
    assert not mock_execute_run.called


@patch("app.web.start_pipeline_job", side_effect=RuntimeError("no credentials"))
def test_run_now_shows_error_when_job_start_fails(
    mock_start_job: MagicMock, cloud_run_client: TestClient
) -> None:
    response = cloud_run_client.post("/ui/runs/run-now")

    assert response.status_code == 200
    assert "start the pipeline job" in response.text


def test_runs_list_shows_started_message(cloud_run_client: TestClient) -> None:
    response = cloud_run_client.get("/ui/runs?started=true")

    assert "Run started" in response.text


def test_settings_hides_schedule_when_managed_by_cloud_scheduler(
    cloud_run_client: TestClient,
) -> None:
    response = cloud_run_client.get("/ui/settings")

    assert 'name="cron_expression"' not in response.text
    assert "Cloud Scheduler" in response.text


def test_settings_save_ignores_schedule_when_managed_by_cloud_scheduler(
    cloud_run_client: TestClient, session_factory
) -> None:
    response = cloud_run_client.post(
        "/ui/settings",
        data={"interest_profile": "AI", "relevance_threshold": "6", "cron_expression": "* * * * *"},
    )

    assert response.status_code == 200
    from pipeline import settings_store

    with session_factory() as db:
        assert settings_store.get_interest_profile(db) == "AI"
        assert settings_store.get_cron_expression(db) == settings_store.DEFAULT_CRON_EXPRESSION


def test_issues_list_empty(client: TestClient) -> None:
    response = client.get("/ui/issues")

    assert response.status_code == 200
    assert "No issues yet" in response.text


def test_issues_list_shows_issue(client: TestClient, session_factory) -> None:
    with session_factory() as db:
        from app.models import Issue

        db.add(
            Issue(
                issue_date=datetime(2026, 9, 21, tzinfo=UTC),
                file_ref="/data/issue.epub",
                article_count=4,
                size_bytes=204800,
            )
        )
        db.commit()

    response = client.get("/ui/issues")

    assert "2026-09-21" in response.text
    assert "200.0 KB" in response.text
    assert "download" in response.text
