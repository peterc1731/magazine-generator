from sqlalchemy.orm import Session

from app.models import Article, ArticleStatus
from pipeline.classification import ClassificationResult


def apply_classification_results(
    db: Session, results: list[ClassificationResult], threshold: float
) -> None:
    """Writes relevance scores/sections back to `articles` and flips each
    one's status to included/excluded against the given threshold
    (ARCHITECTURE.md §3.5). An article flagged as a duplicate of another one
    in the same batch is always excluded, regardless of its own score — we
    never want two copies of the same story in an issue."""
    for result in results:
        article = db.get(Article, result.id)
        if article is None:
            continue
        article.relevance_score = result.relevance_score
        article.section = result.section
        if result.duplicate_of is not None:
            article.status = ArticleStatus.EXCLUDED
        else:
            included = result.relevance_score >= threshold
            article.status = ArticleStatus.INCLUDED if included else ArticleStatus.EXCLUDED
    db.commit()
