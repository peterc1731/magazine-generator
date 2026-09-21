from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import httpx

from connectors.base import FetchResult, RawItem

GUARDIAN_API_BASE = "https://content.guardianapis.com/search"


@dataclass
class GuardianAPIConfig:
    api_key: str
    section: str | None = None
    page_size: int = 20


class GuardianAPIConnector:
    """Fetches articles from the Guardian Open Platform API.

    The API returns clean article HTML directly (`fields.body`), so unlike
    scraped sources this connector's items don't need to go through
    `pipeline.extraction` — `RawItem.cleaned_html` is already usable.
    """

    def __init__(self, config: GuardianAPIConfig, client: httpx.Client | None = None) -> None:
        self._config = config
        self._client = client or httpx.Client(timeout=10.0)

    def fetch_since(self, cursor: str | None) -> FetchResult:
        cursor_dt = _parse_cursor(cursor)
        params: dict[str, str | int] = {
            "api-key": self._config.api_key,
            "order-by": "oldest",
            "page-size": self._config.page_size,
            "show-fields": "byline,body",
        }
        if self._config.section:
            params["section"] = self._config.section
        if cursor_dt is not None:
            params["from-date"] = cursor_dt.date().isoformat()

        response = self._client.get(GUARDIAN_API_BASE, params=params)
        response.raise_for_status()
        results = response.json()["response"]["results"]

        items: list[RawItem] = []
        latest = cursor_dt
        for result in results:
            published_at = _parse_cursor(result["webPublicationDate"])
            if published_at is None or (cursor_dt is not None and published_at <= cursor_dt):
                continue

            fields = result.get("fields", {})
            items.append(
                RawItem(
                    source_item_id=result["id"],
                    title=result.get("webTitle", "Untitled"),
                    url=result["webUrl"],
                    published_at=published_at,
                    author=fields.get("byline"),
                    cleaned_html=fields.get("body"),
                    raw=result,
                )
            )
            if latest is None or published_at > latest:
                latest = published_at

        next_cursor = latest.isoformat() if latest is not None else cursor
        return FetchResult(items=items, next_cursor=next_cursor)


def _parse_cursor(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
