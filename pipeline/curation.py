from sqlalchemy.orm import Session

from app.models import Article, ArticleStatus
from pipeline.classification import ClassificationResult


def apply_classification_results(
    db: Session, results: list[ClassificationResult], threshold: float
) -> None:
    """Writes relevance scores/sections back to `articles` and flips each
    one's status to included/excluded against the given threshold
    (ARCHITECTURE.md §3.5)."""
    for result in results:
        article = db.get(Article, result.id)
        if article is None:
            continue
        article.relevance_score = result.relevance_score
        article.section = result.section
        included = result.relevance_score >= threshold
        article.status = ArticleStatus.INCLUDED if included else ArticleStatus.EXCLUDED
    db.commit()
