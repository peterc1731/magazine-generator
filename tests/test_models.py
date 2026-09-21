from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Article,
    ArticleStatus,
    Issue,
    IssueArticle,
    JobRun,
    JobStatus,
    Setting,
    Source,
    SourceType,
)


def test_create_source_and_article(db_session: Session) -> None:
    source = Source(
        name="The Guardian", type=SourceType.GUARDIAN_API, config={"section": "technology"}
    )
    db_session.add(source)
    db_session.flush()

    article = Article(
        source_id=source.id,
        canonical_url="https://www.theguardian.com/technology/example",
        content_hash="hash-1",
        title="Example Article",
    )
    db_session.add(article)
    db_session.commit()

    assert article.status == ArticleStatus.PENDING
    assert article.source.name == "The Guardian"
    assert source.articles == [article]


def test_article_unique_source_content_hash(db_session: Session) -> None:
    source = Source(name="BBC News", type=SourceType.RSS, config={"feed_url": "https://bbc.co.uk/rss"})
    db_session.add(source)
    db_session.flush()

    db_session.add(
        Article(
            source_id=source.id, canonical_url="https://bbc.co.uk/a", content_hash="dup", title="A"
        )
    )
    db_session.commit()

    db_session.add(
        Article(
            source_id=source.id, canonical_url="https://bbc.co.uk/b", content_hash="dup", title="B"
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_issue_articles_ordered_by_chapter_order(db_session: Session) -> None:
    source = Source(name="Dense Discovery", type=SourceType.WEB_ARCHIVE, config={})
    db_session.add(source)
    db_session.flush()

    first = Article(source_id=source.id, canonical_url="https://a", content_hash="a", title="First")
    second = Article(
        source_id=source.id, canonical_url="https://b", content_hash="b", title="Second"
    )
    db_session.add_all([first, second])
    db_session.flush()

    issue = Issue(issue_date=datetime(2026, 1, 1))
    db_session.add(issue)
    db_session.flush()

    db_session.add_all(
        [
            IssueArticle(issue_id=issue.id, article_id=second.id, chapter_order=1),
            IssueArticle(issue_id=issue.id, article_id=first.id, chapter_order=0),
        ]
    )
    db_session.commit()

    ordered_titles = [link.article.title for link in issue.articles]
    assert ordered_titles == ["First", "Second"]


def test_job_run_defaults(db_session: Session) -> None:
    job_run = JobRun()
    db_session.add(job_run)
    db_session.commit()

    assert job_run.status == JobStatus.RUNNING
    assert job_run.articles_found == 0
    assert job_run.articles_included == 0
    assert job_run.articles_excluded == 0


def test_setting_roundtrip(db_session: Session) -> None:
    db_session.add(Setting(key="cron_expression", value="0 8 * * MON"))
    db_session.commit()

    fetched = db_session.get(Setting, "cron_expression")
    assert fetched is not None
    assert fetched.value == "0 8 * * MON"
