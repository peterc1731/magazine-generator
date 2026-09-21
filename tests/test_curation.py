from sqlalchemy.orm import Session

from app.models import Article, ArticleStatus, Source, SourceType
from pipeline.classification import ClassificationResult
from pipeline.curation import apply_classification_results


def _make_article(db: Session, article_id_suffix: str) -> Article:
    source = Source(name=f"Source {article_id_suffix}", type=SourceType.GUARDIAN_API, config={})
    db.add(source)
    db.flush()
    article = Article(
        source_id=source.id,
        canonical_url=f"https://example.com/{article_id_suffix}",
        content_hash=article_id_suffix,
        title=f"Article {article_id_suffix}",
    )
    db.add(article)
    db.flush()
    return article


def test_apply_classification_results_marks_included_above_threshold(db_session: Session) -> None:
    article = _make_article(db_session, "1")
    results = [ClassificationResult(id=article.id, relevance_score=8.0, section="Tech")]

    apply_classification_results(db_session, results, threshold=5.0)

    db_session.refresh(article)
    assert article.status == ArticleStatus.INCLUDED
    assert article.relevance_score == 8.0
    assert article.section == "Tech"


def test_apply_classification_results_marks_excluded_below_threshold(db_session: Session) -> None:
    article = _make_article(db_session, "2")
    results = [ClassificationResult(id=article.id, relevance_score=2.0, section="Sports")]

    apply_classification_results(db_session, results, threshold=5.0)

    db_session.refresh(article)
    assert article.status == ArticleStatus.EXCLUDED


def test_apply_classification_results_score_equal_to_threshold_is_included(
    db_session: Session,
) -> None:
    article = _make_article(db_session, "3")
    results = [ClassificationResult(id=article.id, relevance_score=5.0, section="Tech")]

    apply_classification_results(db_session, results, threshold=5.0)

    db_session.refresh(article)
    assert article.status == ArticleStatus.INCLUDED


def test_apply_classification_results_ignores_unknown_article_id(db_session: Session) -> None:
    results = [ClassificationResult(id="does-not-exist", relevance_score=9.0, section="Tech")]

    apply_classification_results(db_session, results, threshold=5.0)  # should not raise
