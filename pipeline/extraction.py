from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin

import trafilatura
from bs4 import BeautifulSoup, Comment, Tag
from lxml import etree


@dataclass
class ExtractedArticle:
    title: str
    author: str | None
    published_at: datetime | None
    plaintext: str
    cleaned_html: str


def extract_article(html: str, url: str) -> ExtractedArticle | None:
    """Strip boilerplate (nav/ads/footers) and pull out article content + metadata.

    Returns None when trafilatura can't find any extractable content at all.
    Low-confidence/short extractions (e.g. JS-rendered pages) aren't specially
    handled here — that's the Playwright fallback tracked as a later task.
    """
    output = trafilatura.extract(
        html,
        url=url,
        output_format="html",
        with_metadata=True,
        favor_precision=True,
        include_images=True,
    )
    if not output:
        return None

    tree = etree.fromstring(output.encode("utf-8"))
    body = tree.find(".//body")
    if body is None or len(body) == 0:
        return None

    meta = {el.get("name"): el.get("content") for el in tree.findall(".//meta") if el.get("name")}
    # Pages often use relative image/link paths; the epub builder can only
    # download (and the e-reader can only follow) absolute ones.
    for element in body.iter():
        for attribute in ("src", "href"):
            if element.get(attribute):
                element.set(attribute, urljoin(url, element.get(attribute).strip()))
    cleaned_html = "".join(
        etree.tostring(child, encoding="unicode", method="html").strip() for child in body
    )
    plaintext = " ".join(" ".join(body.itertext()).split())

    return ExtractedArticle(
        title=meta.get("title") or "Untitled",
        author=meta.get("author"),
        published_at=_parse_date(meta.get("date")),
        plaintext=plaintext,
        cleaned_html=cleaned_html,
    )


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None


# --- Newsletter mode -----------------------------------------------------------

# Elements kept as blocks, in document order. Everything else (the nested
# layout tables email templates are built from, spacer cells, wrapper
# spans/divs) is walked through rather than kept.
_BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "blockquote", "pre", "img"}
_SKIP_TAGS = {"head", "script", "style", "noscript", "title", "meta", "link"}
_INLINE_TAGS_KEPT = {"a", "b", "strong", "i", "em", "br", "img", "code", "li", "sub", "sup"}
_ATTRIBUTES_KEPT = {"href", "src", "alt"}
_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")


def extract_newsletter(
    html: str, url: str, remove_selectors: list[str] | None = None
) -> ExtractedArticle | None:
    """Extraction for email-template newsletters (e.g. Dense Discovery), whose
    pages are nested layout tables that trafilatura scrambles — it pulls
    section headings away from their content and drops item titles.

    Instead: drop anything matching `remove_selectors` (ads, footers), then
    keep the headings, paragraphs, lists and images in document order,
    flattening the tables around them. Headings are shifted down a level
    (the chapter's own <h1> is the article title), relative links/images are
    resolved against `url`, and headings left with no content under them
    (e.g. a "Sponsor" heading whose ad was removed) are dropped.
    """
    soup = BeautifulSoup(html, "html.parser")
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    title = soup.title.get_text(" ", strip=True) if soup.title else "Untitled"
    # Before removal: the date often lives in a footer that's stripped below.
    published_at = _find_published_date(soup)
    for selector in remove_selectors or []:
        for element in soup.select(selector):
            element.decompose()

    blocks = [_clean_block(block, url) for block in _collect_blocks(soup.body or soup)]
    blocks = _drop_empty_sections([block for block in blocks if _has_content(block)])
    if not blocks:
        return None

    cleaned_html = "".join(str(block) for block in blocks)
    plaintext = " ".join(" ".join(block.get_text(" ") for block in blocks).split())
    return ExtractedArticle(
        title=title or "Untitled",
        author=None,
        published_at=published_at,
        plaintext=plaintext,
        cleaned_html=cleaned_html,
    )


_PUBLISHED_PATTERN = re.compile(
    r"published\s+(?:on\s+)?([A-Z][a-z]+\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})"
)
_DATE_META_NAMES = ("article:published_time", "date", "pubdate", "publish-date", "dc.date")


def _find_published_date(soup: BeautifulSoup) -> datetime | None:
    """A date from standard <meta>/<time> markup, else from a "published on
    September 29 2026"-style phrase in the text (Dense Discovery's footer)."""
    for meta in soup.find_all("meta"):
        name = (meta.get("property") or meta.get("name") or "").lower()
        if name in _DATE_META_NAMES and meta.get("content"):
            parsed = _parse_iso_date(meta["content"])
            if parsed:
                return parsed
    time_tag = soup.find("time", attrs={"datetime": True})
    if time_tag:
        parsed = _parse_iso_date(time_tag["datetime"])
        if parsed:
            return parsed
    match = _PUBLISHED_PATTERN.search(soup.get_text(" "))
    if match:
        text = re.sub(r"(\d)(st|nd|rd|th)", r"\1", match.group(1)).replace(",", "").replace(".", "")
        for fmt in ("%B %d %Y", "%b %d %Y"):
            try:
                return datetime.strptime(" ".join(text.split()), fmt)
            except ValueError:
                continue
    return None


def _parse_iso_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip()[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _collect_blocks(node: Tag) -> list[Tag]:
    blocks: list[Tag] = []
    for child in node.children:
        if not isinstance(child, Tag) or child.name in _SKIP_TAGS:
            continue
        if child.name in _BLOCK_TAGS:
            blocks.append(child)
        else:
            blocks.extend(_collect_blocks(child))
    return blocks


def _clean_block(block: Tag, base_url: str) -> Tag:
    if block.name in _HEADINGS:
        block.name = f"h{min(int(block.name[1]) + 1, 6)}"
    for element in [block, *block.find_all(True)]:
        if element is not block and element.name not in _INLINE_TAGS_KEPT:
            element.unwrap()  # spans, fonts, nested layout — keep their text
            continue
        element.attrs = {k: v for k, v in element.attrs.items() if k in _ATTRIBUTES_KEPT}
        for attribute in ("href", "src"):
            if element.get(attribute):
                element[attribute] = urljoin(base_url, element[attribute].strip())
    return block


def _has_content(block: Tag) -> bool:
    return bool(block.get_text(strip=True).replace("\xa0", "")) or block.name == "img" or bool(
        block.find("img")
    )


def _drop_empty_sections(blocks: list[Tag]) -> list[Tag]:
    """Drops top-level section headings with nothing under them before the
    next one — e.g. "Sponsor" once its ad has been removed. Only the top
    level: lower headings legitimately stand alone (a social post's
    "@handle" / "on Mastodon" attribution lines)."""
    levels = [int(block.name[1]) for block in blocks if block.name in _HEADINGS]
    if not levels:
        return blocks
    top = f"h{min(levels)}"
    kept: list[Tag] = []
    for index, block in enumerate(blocks):
        following = blocks[index + 1] if index + 1 < len(blocks) else None
        if block.name == top and (following is None or following.name == top):
            continue
        kept.append(block)
    return kept
