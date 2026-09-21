from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass
class RawItem:
    """Content from a source, in whatever shape that source naturally gives it.

    `cleaned_html`/`plaintext` are only populated when the source already
    provides structured content (e.g. the Guardian API) and extraction can be
    skipped; otherwise a caller runs `pipeline.extraction.extract_article`
    against a fetched page for this item's `url`.
    """

    source_item_id: str
    title: str
    url: str
    published_at: datetime | None
    author: str | None = None
    cleaned_html: str | None = None
    plaintext: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchResult:
    items: list[RawItem]
    next_cursor: str | None


class SourceConnector(Protocol):
    def fetch_since(self, cursor: str | None) -> FetchResult:
        """Return items newer than `cursor`, plus the cursor value to persist next."""
        ...
