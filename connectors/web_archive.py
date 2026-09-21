from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from connectors.base import FetchResult, RawItem
from pipeline.extraction import extract_article


@dataclass
class WebArchiveConnectorConfig:
    archive_url: str
    link_selector: str
    """CSS selector (passed to BeautifulSoup.select) matching each issue's <a> tag."""
    initial_fetch_limit: int = 5
    """On a first run (no cursor), only pull the N most recent issues rather
    than the whole archive."""


class WebArchiveConnector:
    """Generic connector for newsletters that publish past issues on their
    website but don't offer RSS (ARCHITECTURE.md §5.3: Dense Discovery,
    bytes.dev). Assumes the archive page lists issues newest-first.
    """

    def __init__(
        self, config: WebArchiveConnectorConfig, client: httpx.Client | None = None
    ) -> None:
        self._config = config
        self._client = client or httpx.Client(timeout=10.0, follow_redirects=True)

    def fetch_since(self, cursor: str | None) -> FetchResult:
        response = self._client.get(self._config.archive_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        new_issue_urls: list[str] = []
        for link in soup.select(self._config.link_selector):
            href = link.get("href")
            if not href:
                continue
            url = urljoin(self._config.archive_url, href)
            if url == cursor:
                break
            new_issue_urls.append(url)
            if cursor is None and len(new_issue_urls) >= self._config.initial_fetch_limit:
                break

        # Collected newest-first; process oldest-to-newest so issue order matches publication order.
        new_issue_urls.reverse()

        items: list[RawItem] = []
        for url in new_issue_urls:
            page = self._client.get(url)
            page.raise_for_status()
            extracted = extract_article(page.text, url=url)
            if extracted is None:
                continue
            items.append(
                RawItem(
                    source_item_id=url,
                    title=extracted.title,
                    url=url,
                    published_at=extracted.published_at,
                    author=extracted.author,
                    cleaned_html=extracted.cleaned_html,
                    plaintext=extracted.plaintext,
                )
            )

        next_cursor = new_issue_urls[-1] if new_issue_urls else cursor
        return FetchResult(items=items, next_cursor=next_cursor)
