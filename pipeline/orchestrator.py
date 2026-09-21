from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import Article, ArticleStatus, Issue, IssueArticle, JobRun, JobStatus, Source
from pipeline.classification import ClassificationInput, classify_articles
from pipeline.connector_factory import build_connector
from pipeline.curation import apply_classification_results
from pipeline.epub_builder import EpubArticleInput, build_epub
from pipeline.ingest import ingest_raw_item
from pipeline.settings_store import get_interest_profile, get_relevance_threshold
from pipeline.storage import load_cleaned_html, save_cover_image

MAX_SUMMARY_CHARS = 1000


def run_pipeline(db: Session, anthropic_client: Any, settings: Settings | None = None) -> JobRun:
    """Runs one full weekly cycle: fetch every enabled source, classify/dedup
    pending articles, and build an issue from whatever ends up included
    (ARCHITECTURE.md §6). A broken source's error is recorded but doesn't
    abort the run — every other source still gets processed.
    """
    settings = settings or get_settings()
    job_run = JobRun(status=JobStatus.RUNNING)
    db.add(job_run)
    db.commit()

    errors: list[str] = []
    articles_found = _fetch_and_ingest_sources(db, settings, errors)
    _included_count, excluded_count = _classify_pending(db, anthropic_client, errors)
    issue = _build_issue_from_included(db, settings, errors)

    job_run.finished_at = datetime.now(UTC)
    job_run.articles_found = articles_found
    job_run.articles_included = issue.article_count if issue else 0
    job_run.articles_excluded = excluded_count
    job_run.status = JobStatus.FAILED if errors else JobStatus.SUCCESS
    job_run.error_summary = "; ".join(errors) if errors else None
    db.commit()

    return job_run


def _fetch_and_ingest_sources(db: Session, settings: Settings, errors: list[str]) -> int:
    """Fetches every enabled source and persists new items as `Article` rows.
    Returns the count of newly ingested articles."""
    ingested = 0
    sources = (
        db.execute(select(Source).where(Source.enabled.is_(True)).order_by(Source.created_at))
        .scalars()
        .all()
    )

    for source in sources:
        try:
            connector = build_connector(source, settings)
            result = connector.fetch_since(source.last_cursor)
        except Exception as exc:  # noqa: BLE001 — per-source isolation, see ARCHITECTURE §6
            errors.append(f"{source.name}: {exc}")
            continue

        for raw_item in result.items:
            if ingest_raw_item(db, source, raw_item) is not None:
                ingested += 1

        source.last_cursor = result.next_cursor
        db.commit()

    return ingested


def _classify_pending(
    db: Session, anthropic_client: Any, errors: list[str]
) -> tuple[int, int]:
    """Classifies every PENDING article in one batched call and applies the
    results. Returns (included_count, excluded_count) for this pass — zero
    for both if there was nothing to classify or the call failed."""
    pending = (
        db.execute(select(Article).where(Article.status == ArticleStatus.PENDING))
        .scalars()
        .all()
    )
    if not pending:
        return 0, 0

    # Source-preference order controls which article "wins" a duplicate
    # (pipeline/classification.py's dedup contract — earlier wins).
    pending = sorted(pending, key=lambda a: (a.source.created_at, a.published_at or a.fetched_at))

    try:
        interest_profile = get_interest_profile(db)
        threshold = get_relevance_threshold(db)
        inputs = [
            ClassificationInput(id=a.id, title=a.title, summary=_summary_for(a)) for a in pending
        ]
        results = classify_articles(anthropic_client, interest_profile, inputs)
        apply_classification_results(db, results, threshold)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"classification: {exc}")
        return 0, 0

    included = sum(1 for r in results if r.duplicate_of is None and r.relevance_score >= threshold)
    return included, len(results) - included


def _build_issue_from_included(
    db: Session, settings: Settings, errors: list[str]
) -> Issue | None:
    """Builds an ePub from every INCLUDED article not already in a past
    issue. Returns None if there's nothing new to publish or the build
    failed (recorded in `errors` either way)."""
    included = (
        db.execute(
            select(Article)
            .where(Article.status == ArticleStatus.INCLUDED)
            .order_by(Article.section, Article.published_at)
        )
        .scalars()
        .all()
    )
    included = [article for article in included if not article.issue_links]
    if not included:
        return None

    try:
        epub_inputs = [
            EpubArticleInput(
                title=article.title,
                source_name=article.source.name,
                html_body=_html_body_for(article),
                author=article.author,
                published_at=article.published_at,
                section=article.section,
            )
            for article in included
        ]
        issue_date = datetime.now(UTC).date()
        output_path = Path(settings.issues_dir) / f"issue-{issue_date.isoformat()}.epub"
        cover_bytes = build_epub(
            epub_inputs, issue_title=f"Magazine — {issue_date.isoformat()}", output_path=output_path
        )

        issue = Issue(
            issue_date=datetime.now(UTC),
            file_ref=str(output_path),
            article_count=len(included),
            size_bytes=output_path.stat().st_size,
        )
        db.add(issue)
        db.flush()  # populates issue.id for the cover file name below
        issue.cover_ref = save_cover_image(issue.id, cover_bytes)
        for order, article in enumerate(included):
            db.add(
                IssueArticle(
                    issue_id=issue.id,
                    article_id=article.id,
                    section=article.section,
                    chapter_order=order,
                )
            )
        db.commit()
        return issue
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        errors.append(f"epub build: {exc}")
        return None


def _html_body_for(article: Article) -> str:
    if article.cleaned_content_ref:
        return load_cleaned_html(article.cleaned_content_ref)
    return f"<p>{article.plaintext or ''}</p>"


def _summary_for(article: Article) -> str:
    return (article.plaintext or "")[:MAX_SUMMARY_CHARS]
