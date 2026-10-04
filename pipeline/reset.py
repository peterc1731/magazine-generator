from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models import Article, Issue, IssueArticle, JobRun, JobStatus, Source

# A RUNNING job_runs row older than this is a crashed run, not a live one —
# the pipeline job's own timeout is an hour (deploy/terraform).
STALE_RUN_AFTER = timedelta(hours=2)


class RunInProgressError(Exception):
    pass


def start_over(db: Session) -> tuple[int, int]:
    """Deletes every issue and article and clears every source's cursor, so
    the next run fetches each source as if for the first time and builds a
    fresh issue — e.g. to redo issues after an extraction change. Sources,
    settings (including stored X tokens) and run history are kept. Also
    removes the deleted rows' files (epubs, covers, cleaned article HTML).

    Returns (issues_deleted, articles_deleted). Refuses while a run is in
    progress, since it would be writing articles as they're deleted.
    """
    cutoff = datetime.now(UTC).replace(tzinfo=None) - STALE_RUN_AFTER
    running = db.execute(
        select(JobRun.id).where(JobRun.status == JobStatus.RUNNING, JobRun.started_at > cutoff)
    ).first()
    if running is not None:
        raise RunInProgressError("A run is in progress — wait for it to finish first.")

    issues = db.execute(select(Issue)).scalars().all()
    articles = db.execute(select(Article)).scalars().all()
    files = [issue.file_ref for issue in issues] + [issue.cover_ref for issue in issues]
    files += [article.cleaned_content_ref for article in articles]

    db.execute(delete(IssueArticle))
    db.execute(delete(Issue))
    db.execute(delete(Article))
    db.execute(update(Source).values(last_cursor=None))
    db.commit()

    for ref in files:
        if ref:
            Path(ref).unlink(missing_ok=True)
    return len(issues), len(articles)
