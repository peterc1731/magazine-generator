from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import httpx

from connectors.base import FetchResult, RawItem
from connectors.x_oauth import refresh_access_token

BOOKMARKS_URL_TEMPLATE = "https://api.x.com/2/users/{user_id}/bookmarks"


@dataclass
class XBookmarksConfig:
    user_id: str
    access_token: str
    client_id: str
    client_secret: str | None = None
    refresh_token: str | None = None
    max_results: int = 100


class XBookmarksConnector:
    """Fetches bookmarks added since the last run (ARCHITECTURE.md §5.4).

    The Bookmarks endpoint has no `since_id`/date filter — it only supports
    paging (newest-first) via `pagination_token`. So this connector pages
    forward from the most recent bookmark until it either runs out of pages
    or reaches the last-seen bookmark id (the cursor).
    """

    def __init__(self, config: XBookmarksConfig, client: httpx.Client | None = None) -> None:
        self._config = config
        self._client = client or httpx.Client(timeout=10.0)

    def fetch_since(self, cursor: str | None) -> FetchResult:
        items: list[RawItem] = []
        newest_id: str | None = None
        pagination_token: str | None = None

        while True:
            params: dict[str, str | int] = {
                "max_results": self._config.max_results,
                "tweet.fields": "created_at",
            }
            if pagination_token:
                params["pagination_token"] = pagination_token

            data = self._get_page(params)
            reached_cursor = False
            for tweet in data.get("data", []):
                if cursor is not None and tweet["id"] == cursor:
                    reached_cursor = True
                    break
                if newest_id is None:
                    newest_id = tweet["id"]
                items.append(
                    RawItem(
                        source_item_id=tweet["id"],
                        title=_first_line(tweet["text"]),
                        url=f"https://x.com/i/web/status/{tweet['id']}",
                        published_at=_parse_created_at(tweet.get("created_at")),
                        plaintext=tweet["text"],
                        raw=tweet,
                    )
                )

            if reached_cursor:
                break
            pagination_token = data.get("meta", {}).get("next_token")
            if not pagination_token:
                break

        # Collected newest-first (API order); reverse so callers get chronological order.
        items.reverse()
        return FetchResult(items=items, next_cursor=newest_id or cursor)

    def _get_page(self, params: dict[str, str | int]) -> dict:
        url = BOOKMARKS_URL_TEMPLATE.format(user_id=self._config.user_id)
        response = self._request(url, params)
        if response.status_code == 401 and self._config.refresh_token:
            self._refresh()
            response = self._request(url, params)
        response.raise_for_status()
        return response.json()

    def _request(self, url: str, params: dict[str, str | int]) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._config.access_token}"}
        return self._client.get(url, params=params, headers=headers)

    def _refresh(self) -> None:
        assert self._config.refresh_token is not None
        payload = refresh_access_token(
            self._client,
            self._config.client_id,
            self._config.refresh_token,
            client_secret=self._config.client_secret,
        )
        self._config.access_token = payload["access_token"]
        self._config.refresh_token = payload.get("refresh_token", self._config.refresh_token)


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0][:120] if text.strip() else "Untitled bookmark"


def _parse_created_at(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
