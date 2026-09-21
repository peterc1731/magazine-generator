from datetime import datetime
from io import BytesIO
from pathlib import Path

import ebooklib
import httpx
import respx
from ebooklib import epub
from PIL import Image

from pipeline.epub_builder import EpubArticleInput, _generate_cover_image, build_epub


def _document_bodies(book: epub.EpubBook) -> list[str]:
    return [
        item.content.decode("utf-8")
        for item in book.get_items()
        if item.get_type() == ebooklib.ITEM_DOCUMENT
    ]


def test_build_epub_creates_one_chapter_per_article_plus_nav_and_cover(tmp_path: Path) -> None:
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
    bodies = _document_bodies(book)
    # 2 article chapters + nav + the generated cover page
    assert len(bodies) == 4

    titles = {article.title for article in articles}
    assert any("First Article" in body and "First body." in body for body in bodies)
    assert any("Second Article" in body and "Second body." in body for body in bodies)
    assert all(any(title in body for body in bodies) for title in titles)


def test_generate_cover_image_handles_em_dash_title() -> None:
    # Regression test: Pillow's bundled fallback bitmap font has no glyph for
    # "—", which used to render as a visible tofu box on the cover.
    image_bytes = _generate_cover_image("Magazine — 2026-09-21")

    image = Image.open(BytesIO(image_bytes))
    assert image.format == "JPEG"
    assert image.size == (1200, 1600)


def test_build_epub_includes_generated_cover_image(tmp_path: Path) -> None:
    articles = [EpubArticleInput(title="A", source_name="S", html_body="<p>body</p>")]
    output_path = tmp_path / "issue.epub"

    returned_cover_bytes = build_epub(articles, issue_title="Test Issue", output_path=output_path)

    book = epub.read_epub(str(output_path))
    covers = [item for item in book.get_items() if item.get_type() == ebooklib.ITEM_COVER]
    assert len(covers) == 1
    assert covers[0].content  # non-empty image bytes
    # The bytes returned to the caller are the same ones embedded in the epub.
    assert returned_cover_bytes == covers[0].content


def test_build_epub_groups_chapters_by_section_in_toc(tmp_path: Path) -> None:
    articles = [
        EpubArticleInput(title="Tech story", source_name="S", html_body="<p>a</p>", section="Tech"),
        EpubArticleInput(
            title="World story", source_name="S", html_body="<p>b</p>", section="World News"
        ),
        EpubArticleInput(
            title="Another tech story", source_name="S", html_body="<p>c</p>", section="Tech"
        ),
    ]
    output_path = tmp_path / "issue.epub"

    build_epub(articles, issue_title="Test Issue", output_path=output_path)

    book = epub.read_epub(str(output_path))
    toc_by_section = {
        section.title: [chapter.title for chapter in chapters] for section, chapters in book.toc
    }

    assert toc_by_section == {
        "Tech": ["Tech story", "Another tech story"],
        "World News": ["World story"],
    }


def test_build_epub_defaults_missing_section_to_uncategorized(tmp_path: Path) -> None:
    articles = [EpubArticleInput(title="No section", source_name="S", html_body="<p>a</p>")]
    output_path = tmp_path / "issue.epub"

    build_epub(articles, issue_title="Test Issue", output_path=output_path)

    book = epub.read_epub(str(output_path))
    section_titles = [section.title for section, _chapters in book.toc]
    assert section_titles == ["Uncategorized"]


@respx.mock
def test_build_epub_rehosts_remote_images(tmp_path: Path) -> None:
    respx.get("https://example.com/photo.jpg").mock(
        return_value=httpx.Response(
            200, content=b"fake-jpeg-bytes", headers={"content-type": "image/jpeg"}
        )
    )
    articles = [
        EpubArticleInput(
            title="Article with image",
            source_name="S",
            html_body='<p>Look:</p><img src="https://example.com/photo.jpg" alt="a photo">',
        )
    ]
    output_path = tmp_path / "issue.epub"

    build_epub(articles, issue_title="Test Issue", output_path=output_path)

    book = epub.read_epub(str(output_path))
    images = [item for item in book.get_items() if item.get_type() == ebooklib.ITEM_IMAGE]
    assert len(images) == 1  # the rehosted photo (the cover is ITEM_COVER, not ITEM_IMAGE)
    rehosted = images[0]
    assert rehosted.content == b"fake-jpeg-bytes"

    bodies = _document_bodies(book)
    chapter_body = next(body for body in bodies if "Article with image" in body)
    assert "https://example.com/photo.jpg" not in chapter_body
    assert rehosted.file_name in chapter_body


@respx.mock
def test_build_epub_drops_image_that_fails_to_fetch(tmp_path: Path) -> None:
    respx.get("https://example.com/broken.jpg").mock(return_value=httpx.Response(404))
    articles = [
        EpubArticleInput(
            title="Article with broken image",
            source_name="S",
            html_body='<p>Look:</p><img src="https://example.com/broken.jpg" alt="broken">',
        )
    ]
    output_path = tmp_path / "issue.epub"

    build_epub(articles, issue_title="Test Issue", output_path=output_path)

    book = epub.read_epub(str(output_path))
    images = [item for item in book.get_items() if item.get_type() == ebooklib.ITEM_IMAGE]
    assert images == []  # the broken image was dropped, only the cover (ITEM_COVER) exists

    bodies = _document_bodies(book)
    chapter_body = next(body for body in bodies if "Article with broken image" in body)
    assert "broken.jpg" not in chapter_body
