from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from connectors.base import FetchResult, RawItem
from pipeline.extraction import ExtractedArticle, extract_article, extract_newsletter

# Numbered mode: most new issues to pull in one run, and the highest issue
# number to probe for. Both guard against a site that answers 200 for any
# number (e.g. a soft "not found" page), which would otherwise loop forever.
MAX_NEW_ISSUES_PER_RUN = 10
MAX_ISSUE_NUMBER = 100_000


@dataclass
class WebArchiveConnectorConfig:
    archive_url: str = ""
    link_selector: str = ""
    """CSS selector (passed to BeautifulSoup.select) matching each issue's <a> tag."""
    initial_fetch_limit: int = 5
    """On a first run (no cursor), only pull the N most recent issues rather
    than the whole archive."""
    issue_url_template: str = ""
    """Numbered mode, for archives whose issue list isn't plain links (e.g.
    built by JavaScript): a URL with a `{number}` placeholder, like
    "https://www.densediscovery.com/archive/{number}/". When set, the
    archive page and selector are ignored; the connector probes issue
    numbers directly, and the cursor is the last issue number seen."""
    content_mode: str = "article"
    """How each issue page is turned into content: "article" (trafilatura,
    for normal article pages) or "newsletter" (keeps headings, paragraphs
    and images in document order — for email-template layouts built from
    nested tables, which trafilatura scrambles)."""
    remove_selectors: list[str] = field(default_factory=list)
    """Newsletter mode: CSS selectors for elements to drop before extracting
    (ads, footers, logos)."""


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
        if self._config.issue_url_template:
            return self._fetch_numbered_since(cursor)

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
            item = self._to_raw_item(page.text, url)
            if item is not None:
                items.append(item)

        next_cursor = new_issue_urls[-1] if new_issue_urls else cursor
        return FetchResult(items=items, next_cursor=next_cursor)

    # --- Numbered mode -------------------------------------------------------

    def _fetch_numbered_since(self, cursor: str | None) -> FetchResult:
        """Assumes issues are numbered contiguously (no gaps), and that a
        missing number answers 404/410 or redirects away from its URL."""
        pages: dict[int, str] = {}
        if cursor is not None and cursor.isdigit():
            number = int(cursor) + 1
            while len(pages) < MAX_NEW_ISSUES_PER_RUN:
                html = self._get_issue(number)
                if html is None:
                    break
                pages[number] = html
                number += 1
        else:
            latest = self._find_latest_issue()
            if latest is None:
                return FetchResult(items=[], next_cursor=cursor)
            first = max(1, latest - self._config.initial_fetch_limit + 1)
            for number in range(first, latest + 1):
                html = self._get_issue(number)
                if html is not None:
                    pages[number] = html

        items = []
        for number in sorted(pages):  # oldest first, matching publication order
            item = self._to_raw_item(pages[number], self._issue_url(number))
            if item is not None:
                items.append(item)

        next_cursor = str(max(pages)) if pages else cursor
        return FetchResult(items=items, next_cursor=next_cursor)

    def _find_latest_issue(self) -> int | None:
        """Highest existing issue number: double until an issue is missing,
        then binary-search the gap — ~2·log2(N) requests instead of N."""
        if self._get_issue(1) is None:
            return None
        found, missing = 1, 2
        while self._get_issue(missing) is not None:
            found, missing = missing, missing * 2
            if missing > MAX_ISSUE_NUMBER:
                raise ValueError(
                    f"Every issue number up to {MAX_ISSUE_NUMBER} seems to exist — the site "
                    "probably answers 200 for missing issues; check the issue URL template"
                )
        while missing - found > 1:
            middle = (found + missing) // 2
            if self._get_issue(middle) is not None:
                found = middle
            else:
                missing = middle
        return found

    def _get_issue(self, number: int) -> str | None:
        """The issue page's HTML, or None if that issue doesn't exist."""
        url = self._issue_url(number)
        response = self._client.get(url)
        if response.status_code in (404, 410):
            return None
        response.raise_for_status()
        if urlsplit(str(response.url)).path.rstrip("/") != urlsplit(url).path.rstrip("/"):
            return None  # redirected elsewhere (e.g. back to the archive) — no such issue
        return response.text

    def _issue_url(self, number: int) -> str:
        return self._config.issue_url_template.format(number=number)


    def _to_raw_item(self, html: str, url: str) -> RawItem | None:
        if self._config.content_mode == "newsletter":
            extracted = extract_newsletter(html, url, self._config.remove_selectors)
        else:
            extracted = extract_article(html, url=url)
        return _raw_item_from(extracted, url)


def _raw_item_from(extracted: ExtractedArticle | None, url: str) -> RawItem | None:
    if extracted is None:
        return None
    return RawItem(
        source_item_id=url,
        title=extracted.title,
        url=url,
        published_at=extracted.published_at,
        author=extracted.author,
        cleaned_html=extracted.cleaned_html,
        plaintext=extracted.plaintext,
    )
