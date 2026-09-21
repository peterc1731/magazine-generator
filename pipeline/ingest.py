import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Article, ArticleStatus, Source
from connectors.base import RawItem
from pipeline.storage import save_cleaned_html


def content_hash_for_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def ingest_raw_item(db: Session, source: Source, raw_item: RawItem) -> Article | None:
    """Persists a `RawItem` as an `Article`, skipping ones already seen for
    this source (same canonical URL) via the `(source_id, content_hash)`
    unique constraint. Returns None when skipped."""
    content_hash = content_hash_for_url(raw_item.url)
    existing = db.execute(
        select(Article).where(
            Article.source_id == source.id, Article.content_hash == content_hash
        )
    ).scalar_one_or_none()
    if existing is not None:
        return None

    article = Article(
        source_id=source.id,
        canonical_url=raw_item.url,
        content_hash=content_hash,
        title=raw_item.title,
        author=raw_item.author,
        published_at=raw_item.published_at,
        plaintext=raw_item.plaintext,
        status=ArticleStatus.PENDING,
    )
    db.add(article)
    db.flush()  # populates article.id (client-side default) for the file name below

    if raw_item.cleaned_html:
        article.cleaned_content_ref = save_cleaned_html(article.id, raw_item.cleaned_html)

    return article
