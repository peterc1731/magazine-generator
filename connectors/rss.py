from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, datetime

import feedparser
import httpx

from connectors.base import FetchResult, RawItem
from pipeline.extraction import extract_article


@dataclass
class RSSConnectorConfig:
    feed_url: str


class RSSConnector:
    """Generic RSS/Atom connector. Feed entries rarely carry the full article
    body, so each new entry's page is fetched and run through
    `pipeline.extraction` (ARCHITECTURE.md §5.1).
    """

    def __init__(self, config: RSSConnectorConfig, client: httpx.Client | None = None) -> None:
        self._config = config
        self._client = client or httpx.Client(timeout=10.0, follow_redirects=True)

    def fetch_since(self, cursor: str | None) -> FetchResult:
        response = self._client.get(self._config.feed_url)
        response.raise_for_status()
        feed = feedparser.parse(response.content)

        cursor_dt = _parse_cursor(cursor)
        items: list[RawItem] = []
        latest = cursor_dt

        for entry in feed.entries:
            published_at = _entry_published_at(entry)
            if published_at is None or (cursor_dt is not None and published_at <= cursor_dt):
                continue

            link = entry.get("link")
            if not link:
                continue

            page = self._client.get(link)
            page.raise_for_status()
            extracted = extract_article(page.text, url=link)

            items.append(
                RawItem(
                    source_item_id=entry.get("id", link),
                    title=(extracted.title if extracted else entry.get("title", "Untitled")),
                    url=link,
                    published_at=published_at,
                    author=extracted.author if extracted else entry.get("author"),
                    cleaned_html=extracted.cleaned_html if extracted else None,
                    plaintext=extracted.plaintext if extracted else None,
                    raw=dict(entry),
                )
            )
            if latest is None or published_at > latest:
                latest = published_at

        next_cursor = latest.isoformat() if latest is not None else cursor
        return FetchResult(items=items, next_cursor=next_cursor)


def _entry_published_at(entry: feedparser.FeedParserDict) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed is None:
        return None
    return datetime.fromtimestamp(calendar.timegm(parsed), tz=UTC)


def _parse_cursor(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
