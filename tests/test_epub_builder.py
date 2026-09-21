from datetime import datetime
from pathlib import Path

import ebooklib
from ebooklib import epub

from pipeline.epub_builder import EpubArticleInput, build_epub


def test_build_epub_creates_one_chapter_per_article(tmp_path: Path) -> None:
    articles = [
        EpubArticleInput(
            title="First Article",
            source_name="The Guardian",
            html_body="<p>First body.</p>",
            author="Alex Reporter",
            published_at=datetime(2026, 9, 18),
        ),
        EpubArticleInput(
            title="Second Article",
            source_name="The Guardian",
            html_body="<p>Second body.</p>",
            author="Sam Writer",
            published_at=datetime(2026, 9, 20),
        ),
    ]
    output_path = tmp_path / "issue.epub"

    build_epub(articles, issue_title="Test Issue", output_path=output_path)

    assert output_path.exists()

    book = epub.read_epub(str(output_path))
    chapters = [item for item in book.get_items() if item.get_type() == ebooklib.ITEM_DOCUMENT]
    # 2 article chapters + the nav document
    assert len(chapters) == 3

    titles = {article.title for article in articles}
    bodies = [item.content.decode("utf-8") for item in chapters]
    assert any("First Article" in body and "First body." in body for body in bodies)
    assert any("Second Article" in body and "Second body." in body for body in bodies)
    assert all(any(title in body for body in bodies) for title in titles)
