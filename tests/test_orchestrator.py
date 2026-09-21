import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx
from ebooklib import epub
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Article, ArticleStatus, JobStatus, Source, SourceType
from pipeline.orchestrator import run_pipeline

FEED_URL = "https://example.com/rss/feed.xml"
ARTICLE_URL = "https://example.com/articles/story-1"
BROKEN_FEED_URL = "https://example.com/rss/broken-feed.xml"

FEED_XML = f"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Feed snippet title</title>
    <link>{ARTICLE_URL}</link>
    <guid>{ARTICLE_URL}</guid>
    <pubDate>Fri, 18 Sep 2026 09:00:00 GMT</pubDate>
  </item>
</channel></rss>"""

ARTICLE_HTML = """<html><head>
<meta name="author" content="Jane Doe">
<meta property="article:published_time" content="2026-09-18T09:00:00Z">
</head><body>
<article><h1>Full Story Title</h1><p>Full article body content here.</p></article>
</body></html>"""


class FakeMessages:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text

    def create(self, **kwargs: Any) -> Any:
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.response_text)])


class FakeClient:
    def __init__(self, response_text: str) -> None:
        self.messages = FakeMessages(response_text)


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ISSUES_DIR", str(tmp_path / "output"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_working_source(db: Session) -> Source:
    source = Source(name="Working Feed", type=SourceType.RSS, config={"feed_url": FEED_URL})
    db.add(source)
    db.flush()
    return source


def _make_broken_source(db: Session) -> Source:
    source = Source(
        name="Broken Feed", type=SourceType.RSS, config={"feed_url": BROKEN_FEED_URL}
    )
    db.add(source)
    db.flush()
    return source


def _mock_working_feed() -> None:
    respx.get(FEED_URL).mock(return_value=httpx.Response(200, text=FEED_XML))
    respx.get(ARTICLE_URL).mock(return_value=httpx.Response(200, text=ARTICLE_HTML))


@respx.mock
def test_run_pipeline_ingests_article_and_records_success_with_no_matches(
    db_session: Session,
) -> None:
    source = _make_working_source(db_session)
    _mock_working_feed()

    job_run = run_pipeline(db_session, FakeClient(json.dumps([])), settings=get_settings())

    assert job_run.status == JobStatus.SUCCESS
    assert job_run.articles_found == 1
    assert job_run.articles_included == 0  # nothing classified as included yet
    db_session.refresh(source)
    assert source.last_cursor is not None


@respx.mock
def test_run_pipeline_classifies_and_publishes_ingested_article(db_session: Session) -> None:
    _mock_working_feed()
    _make_working_source(db_session)

    # First pass with a no-op classifier just to ingest, so we know the real id.
    run_pipeline(db_session, FakeClient(json.dumps([])), settings=get_settings())

    article = db_session.query(Article).one()
    fake_anthropic = FakeClient(
        json.dumps([{"id": article.id, "relevance_score": 9, "section": "Tech"}])
    )

    job_run = run_pipeline(db_session, fake_anthropic, settings=get_settings())

    assert job_run.status == JobStatus.SUCCESS
    assert job_run.articles_included == 1
    db_session.refresh(article)
    assert article.status == ArticleStatus.INCLUDED
    assert article.section == "Tech"
    assert len(article.issue_links) == 1

    issue = article.issue_links[0].issue
    assert Path(issue.file_ref).exists()
    book = epub.read_epub(issue.file_ref)
    assert book.get_metadata("DC", "title")


@respx.mock
def test_run_pipeline_isolates_broken_source_and_still_processes_others(
    db_session: Session,
) -> None:
    _mock_working_feed()
    _make_working_source(db_session)
    _make_broken_source(db_session)  # BROKEN_FEED_URL is never mocked

    job_run = run_pipeline(db_session, FakeClient(json.dumps([])), settings=get_settings())

    assert job_run.status == JobStatus.FAILED
    assert job_run.error_summary is not None
    assert "Broken Feed" in job_run.error_summary
    assert job_run.articles_found == 1  # the working source's article still got ingested


@respx.mock
def test_run_pipeline_second_run_does_not_duplicate_issue(db_session: Session) -> None:
    _mock_working_feed()
    source = _make_working_source(db_session)
    run_pipeline(db_session, FakeClient(json.dumps([])), settings=get_settings())

    article = db_session.query(Article).one()
    fake_anthropic = FakeClient(
        json.dumps([{"id": article.id, "relevance_score": 9, "section": "Tech"}])
    )
    first = run_pipeline(db_session, fake_anthropic, settings=get_settings())
    assert first.articles_included == 1

    # Second run: same source, but respx has no new items configured beyond
    # what's already been fetched (cursor moved on), and the article is
    # already linked to an issue — nothing new should be published again.
    second = run_pipeline(db_session, FakeClient(json.dumps([])), settings=get_settings())

    assert second.articles_included == 0
    assert source.last_cursor is not None
