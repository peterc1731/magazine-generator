from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
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
from pipeline.reset import RunInProgressError, start_over


def _seed(db: Session, tmp_path: Path) -> tuple[Source, list[Path]]:
    files = [tmp_path / name for name in ("issue.epub", "cover.jpg", "article.html")]
    for file in files:
        file.write_text("x")
    source = Source(
        name="Dense Discovery", type=SourceType.WEB_ARCHIVE, config={}, last_cursor="408"
    )
    db.add(source)
    db.flush()
    article = Article(
        source_id=source.id,
        canonical_url="https://www.densediscovery.com/archive/408/",
        content_hash="abc",
        title="Issue 408",
        status=ArticleStatus.INCLUDED,
        cleaned_content_ref=str(files[2]),
    )
    issue = Issue(issue_date=datetime(2026, 10, 4), file_ref=str(files[0]), cover_ref=str(files[1]))
    db.add_all([article, issue, Setting(key="interest_profile", value="AI")])
    db.flush()
    db.add(IssueArticle(issue_id=issue.id, article_id=article.id))
    db.add(JobRun(status=JobStatus.SUCCESS, finished_at=datetime(2026, 10, 4)))
    db.commit()
    return source, files


def _count(db: Session, model) -> int:
    return db.execute(select(func.count()).select_from(model)).scalar_one()


def test_start_over_deletes_issues_and_articles_and_resets_cursors(
    db_session: Session, tmp_path: Path
) -> None:
    source, files = _seed(db_session, tmp_path)

    assert start_over(db_session) == (1, 1)

    assert _count(db_session, Issue) == 0
    assert _count(db_session, Article) == 0
    assert _count(db_session, IssueArticle) == 0
    db_session.refresh(source)
    assert source.last_cursor is None
    assert not any(file.exists() for file in files)


def test_start_over_keeps_sources_settings_and_run_history(
    db_session: Session, tmp_path: Path
) -> None:
    _seed(db_session, tmp_path)

    start_over(db_session)

    assert _count(db_session, Source) == 1
    assert db_session.get(Setting, "interest_profile").value == "AI"
    assert _count(db_session, JobRun) == 1


def test_start_over_refuses_while_a_run_is_in_progress(
    db_session: Session, tmp_path: Path
) -> None:
    _seed(db_session, tmp_path)
    db_session.add(JobRun(status=JobStatus.RUNNING))
    db_session.commit()

    with pytest.raises(RunInProgressError):
        start_over(db_session)
    assert _count(db_session, Issue) == 1


def test_start_over_ignores_a_long_dead_running_row(db_session: Session, tmp_path: Path) -> None:
    _seed(db_session, tmp_path)
    crashed = JobRun(status=JobStatus.RUNNING, started_at=datetime.utcnow() - timedelta(hours=5))
    db_session.add(crashed)
    db_session.commit()

    assert start_over(db_session) == (1, 1)
