from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ArticleStatus, Source, SourceType
from connectors.base import RawItem
from pipeline.ingest import content_hash_for_url, ingest_raw_item
from pipeline.storage import load_cleaned_html


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_source(db: Session) -> Source:
    source = Source(name="The Guardian", type=SourceType.GUARDIAN_API, config={})
    db.add(source)
    db.flush()
    return source


def test_ingest_raw_item_creates_article_with_cleaned_html_on_disk(db_session: Session) -> None:
    source = _make_source(db_session)
    raw_item = RawItem(
        source_item_id="1",
        title="A story",
        url="https://example.com/a",
        published_at=datetime(2026, 9, 18),
        author="Jane Doe",
        cleaned_html="<p>body</p>",
        plaintext="body",
    )

    article = ingest_raw_item(db_session, source, raw_item)

    assert article is not None
    assert article.status == ArticleStatus.PENDING
    assert article.content_hash == content_hash_for_url("https://example.com/a")
    assert article.cleaned_content_ref is not None
    assert load_cleaned_html(article.cleaned_content_ref) == "<p>body</p>"


def test_ingest_raw_item_skips_already_seen_url(db_session: Session) -> None:
    source = _make_source(db_session)
    raw_item = RawItem(
        source_item_id="1", title="A story", url="https://example.com/a", published_at=None
    )

    first = ingest_raw_item(db_session, source, raw_item)
    second = ingest_raw_item(db_session, source, raw_item)

    assert first is not None
    assert second is None


def test_ingest_raw_item_without_cleaned_html_leaves_ref_none(db_session: Session) -> None:
    source = _make_source(db_session)
    raw_item = RawItem(
        source_item_id="1",
        title="Bookmarked post",
        url="https://x.com/i/web/status/1",
        published_at=None,
        plaintext="just tweet text",
    )

    article = ingest_raw_item(db_session, source, raw_item)

    assert article is not None
    assert article.cleaned_content_ref is None
    assert article.plaintext == "just tweet text"


def test_ingest_raw_item_same_url_different_sources_both_saved(db_session: Session) -> None:
    guardian = _make_source(db_session)
    bbc = Source(name="BBC News", type=SourceType.RSS, config={})
    db_session.add(bbc)
    db_session.flush()

    raw_item = RawItem(
        source_item_id="1", title="Same URL", url="https://example.com/a", published_at=None
    )

    first = ingest_raw_item(db_session, guardian, raw_item)
    second = ingest_raw_item(db_session, bbc, raw_item)

    assert first is not None
    assert second is not None
    assert first.id != second.id
