from __future__ import annotations

import itertools
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from ebooklib import epub
from PIL import Image, ImageDraw, ImageFont

COVER_SIZE = (1200, 1600)
UNSECTIONED_LABEL = "Uncategorized"

_IMAGE_EXTENSION_BY_CONTENT_TYPE = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
}


@dataclass
class EpubArticleInput:
    title: str
    source_name: str
    html_body: str
    author: str | None = None
    published_at: datetime | None = None
    section: str | None = None


def build_epub(
    articles: list[EpubArticleInput],
    issue_title: str,
    output_path: Path,
    client: httpx.Client | None = None,
) -> None:
    """Builds the ePub issue: chapters grouped into a nested, section-based
    TOC, a generated cover, and images downloaded and embedded in the epub
    rather than left as remote links an offline e-reader can't fetch
    (ARCHITECTURE.md §3.6).

    Articles are grouped under their `section` in the order sections first
    appear in `articles` — callers control section order via input order.
    """
    owns_client = client is None
    client = client or httpx.Client(timeout=10.0, follow_redirects=True)
    image_ids = itertools.count()

    try:
        book = epub.EpubBook()
        book.set_identifier(f"magazine-generator-{datetime.utcnow().isoformat()}")
        book.set_title(issue_title)
        book.set_language("en")
        book.set_cover("cover.jpg", _generate_cover_image(issue_title))

        sections: dict[str, list[epub.EpubHtml]] = {}
        for index, article in enumerate(articles):
            rehosted_body = _rehost_images(book, article.html_body, client, image_ids)
            chapter = epub.EpubHtml(
                title=article.title, file_name=f"chapter_{index}.xhtml", lang="en"
            )
            chapter.content = _render_chapter(article, rehosted_body)
            book.add_item(chapter)
            sections.setdefault(article.section or UNSECTIONED_LABEL, []).append(chapter)

        book.toc = [
            (epub.Section(section_name), chapters) for section_name, chapters in sections.items()
        ]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        all_chapters = [chapter for chapters in sections.values() for chapter in chapters]
        book.spine = ["cover", "nav", *all_chapters]

        output_path.parent.mkdir(parents=True, exist_ok=True)
        epub.write_epub(str(output_path), book)
    finally:
        if owns_client:
            client.close()


def _render_chapter(article: EpubArticleInput, html_body: str) -> str:
    byline_parts = [part for part in (article.author, article.source_name) if part]
    if article.published_at:
        byline_parts.append(article.published_at.strftime("%d %B %Y"))
    byline = " · ".join(byline_parts)

    return f"""<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{article.title}</title></head>
<body>
<h1>{article.title}</h1>
<p class="byline"><em>{byline}</em></p>
{html_body}
</body>
</html>"""


def _rehost_images(
    book: epub.EpubBook, html_body: str, client: httpx.Client, image_ids: Iterator[int]
) -> str:
    """Downloads each remote <img> in `html_body` and rewrites its src to a
    local file added to the book's manifest. An image that fails to fetch or
    isn't recognized as an image is dropped rather than left dangling.
    """
    soup = BeautifulSoup(html_body, "html.parser")
    for img in soup.find_all("img"):
        src = img.get("src")
        if not src or not src.startswith(("http://", "https://")):
            continue

        image_bytes, media_type = _fetch_image(client, src)
        if image_bytes is None:
            img.decompose()
            continue

        image_id = next(image_ids)
        extension = _IMAGE_EXTENSION_BY_CONTENT_TYPE[media_type]
        file_name = f"images/img_{image_id}.{extension}"
        book.add_item(
            epub.EpubImage(
                uid=f"img_{image_id}",
                file_name=file_name,
                media_type=media_type,
                content=image_bytes,
            )
        )
        img["src"] = file_name

    return str(soup)


def _fetch_image(client: httpx.Client, url: str) -> tuple[bytes | None, str]:
    try:
        response = client.get(url)
        response.raise_for_status()
    except httpx.HTTPError:
        return None, ""

    media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type not in _IMAGE_EXTENSION_BY_CONTENT_TYPE:
        return None, ""
    return response.content, media_type


_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    # Pillow's bundled fallback font is missing glyphs for characters like
    # "—", so callers should stick to plain ASCII when this path is hit.
    return ImageFont.load_default(size=size)


def _generate_cover_image(issue_title: str) -> bytes:
    image = Image.new("RGB", COVER_SIZE, color=(24, 28, 38))
    draw = ImageDraw.Draw(image)

    # Normalize dashes: the fallback font (no system TTF found) can't render
    # "—"/"–", so avoid depending on which font actually loaded.
    title = issue_title.replace("—", "-").replace("–", "-")
    font = _load_font(size=72)

    bbox = draw.textbbox((0, 0), title, font=font)
    text_width = bbox[2] - bbox[0]
    x = max(80, (COVER_SIZE[0] - text_width) // 2)
    draw.text((x, 700), title, font=font, fill=(255, 255, 255))
    draw.line([(80, 800), (COVER_SIZE[0] - 80, 800)], fill=(90, 95, 115), width=2)

    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()
