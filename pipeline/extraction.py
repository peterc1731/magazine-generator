from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import trafilatura
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
    )
    if not output:
        return None

    tree = etree.fromstring(output.encode("utf-8"))
    body = tree.find(".//body")
    if body is None or len(body) == 0:
        return None

    meta = {el.get("name"): el.get("content") for el in tree.findall(".//meta") if el.get("name")}
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
