from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings, get_settings
from app.db import get_db
from app.main import app
from app.models import Base, Issue


@pytest.fixture
def session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path}/opds-test.db")
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


def _make_issue(session_factory, tmp_path: Path, with_cover: bool = True) -> Issue:
    epub_path = tmp_path / "issue.epub"
    epub_path.write_bytes(b"fake-epub-bytes")
    cover_path = None
    if with_cover:
        cover_path = tmp_path / "cover.jpg"
        cover_path.write_bytes(b"fake-jpeg-bytes")

    with session_factory() as db:
        issue = Issue(
            issue_date=datetime(2026, 9, 21, tzinfo=UTC),
            file_ref=str(epub_path),
            cover_ref=str(cover_path) if cover_path else None,
            article_count=3,
        )
        db.add(issue)
        db.commit()
        db.refresh(issue)
        return issue


def test_catalog_empty_returns_valid_feed(client: TestClient) -> None:
    response = client.get("/opds/")

    assert response.status_code == 200
    assert "opds-catalog" in response.headers["content-type"]
    assert b"<feed" in response.content
    assert b"<entry>" not in response.content


def test_catalog_lists_issue_with_acquisition_and_cover_links(
    client: TestClient, session_factory, tmp_path: Path
) -> None:
    issue = _make_issue(session_factory, tmp_path)

    response = client.get("/opds/")

    body = response.text
    assert f"/opds/issues/{issue.id}/download" in body
    assert f"/opds/issues/{issue.id}/cover" in body
    assert "http://opds-spec.org/acquisition" in body
    assert "application/epub+zip" in body
    assert "3 article(s)" in body


def test_catalog_omits_cover_links_when_no_cover(
    client: TestClient, session_factory, tmp_path: Path
) -> None:
    _make_issue(session_factory, tmp_path, with_cover=False)

    response = client.get("/opds/")

    assert "http://opds-spec.org/image" not in response.text


def test_download_issue_returns_epub_bytes(
    client: TestClient, session_factory, tmp_path: Path
) -> None:
    issue = _make_issue(session_factory, tmp_path)

    response = client.get(f"/opds/issues/{issue.id}/download")

    assert response.status_code == 200
    assert response.content == b"fake-epub-bytes"
    assert response.headers["content-type"] == "application/epub+zip"


def test_download_unknown_issue_returns_404(client: TestClient) -> None:
    response = client.get("/opds/issues/does-not-exist/download")

    assert response.status_code == 404


def test_cover_returns_image_bytes(client: TestClient, session_factory, tmp_path: Path) -> None:
    issue = _make_issue(session_factory, tmp_path)

    response = client.get(f"/opds/issues/{issue.id}/cover")

    assert response.status_code == 200
    assert response.content == b"fake-jpeg-bytes"


def test_cover_missing_returns_404(client: TestClient, session_factory, tmp_path: Path) -> None:
    issue = _make_issue(session_factory, tmp_path, with_cover=False)

    response = client.get(f"/opds/issues/{issue.id}/cover")

    assert response.status_code == 404


def test_auth_open_when_not_configured(client: TestClient) -> None:
    # The `client` fixture's Settings() has blank auth fields by default.
    response = client.get("/opds/")

    assert response.status_code == 200


def test_auth_rejects_missing_credentials_when_configured(
    session_factory, tmp_path: Path
) -> None:
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
        client = TestClient(app)
        response = client.get("/opds/")
        assert response.status_code == 401

        wrong = client.get("/opds/", auth=("alice", "wrong-password"))
        assert wrong.status_code == 401

        right = client.get("/opds/", auth=("alice", "secret"))
        assert right.status_code == 200
    finally:
        app.dependency_overrides.clear()
