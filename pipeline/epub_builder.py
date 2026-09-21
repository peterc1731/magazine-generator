from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ebooklib import epub


@dataclass
class EpubArticleInput:
    title: str
    source_name: str
    html_body: str
    author: str | None = None
    published_at: datetime | None = None


def build_epub(articles: list[EpubArticleInput], issue_title: str, output_path: Path) -> None:
    """Build a minimal ePub: one chapter per article, in the given order.

    No cover image or section grouping yet — that's a later task once the
    classification pipeline assigns sections (ARCHITECTURE.md §3.6).
    """
    book = epub.EpubBook()
    book.set_identifier(f"magazine-generator-{datetime.utcnow().isoformat()}")
    book.set_title(issue_title)
    book.set_language("en")

    chapters = []
    for index, article in enumerate(articles):
        chapter = epub.EpubHtml(
            title=article.title,
            file_name=f"chapter_{index}.xhtml",
            lang="en",
        )
        chapter.content = _render_chapter(article)
        book.add_item(chapter)
        chapters.append(chapter)

    book.toc = chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *chapters]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(output_path), book)


def _render_chapter(article: EpubArticleInput) -> str:
    byline_parts = [part for part in (article.author, article.source_name) if part]
    if article.published_at:
        byline_parts.append(article.published_at.strftime("%d %B %Y"))
    byline = " · ".join(byline_parts)

    return f"""<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{article.title}</title></head>
<body>
<h1>{article.title}</h1>
<p class="byline"><em>{byline}</em></p>
{article.html_body}
</body>
</html>"""
