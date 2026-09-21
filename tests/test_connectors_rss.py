from pathlib import Path

import httpx
import respx

from connectors.rss import RSSConnector, RSSConnectorConfig

FIXTURES = Path(__file__).parent / "fixtures"
FEED_URL = "https://feeds.bbci.co.uk/news/rss.xml"
FIRST_URL = "https://www.bbc.co.uk/news/articles/first-story"
SECOND_URL = "https://www.bbc.co.uk/news/articles/second-story"


def _mock_feed_and_articles() -> None:
    respx.get(FEED_URL).mock(
        return_value=httpx.Response(
            200, content=(FIXTURES / "rss" / "bbc_sample_feed.xml").read_bytes()
        )
    )
    respx.get(FIRST_URL).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "html" / "sample_article.html").read_text()
        )
    )
    respx.get(SECOND_URL).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "html" / "second_article.html").read_text()
        )
    )


@respx.mock
def test_fetch_since_none_extracts_full_articles_for_every_entry() -> None:
    _mock_feed_and_articles()
    connector = RSSConnector(RSSConnectorConfig(feed_url=FEED_URL))

    result = connector.fetch_since(None)

    assert [item.url for item in result.items] == [FIRST_URL, SECOND_URL]
    # Title/author/body come from the full page, not the feed snippet.
    assert result.items[0].title == "Scientists Discover New Method For Widget Production"
    assert result.items[1].title == "Second Story Headline In Full"
    assert result.items[1].author == "Sam Writer"
    assert result.next_cursor == "2026-09-20T11:30:00+00:00"


@respx.mock
def test_fetch_since_cursor_excludes_older_entries() -> None:
    _mock_feed_and_articles()
    connector = RSSConnector(RSSConnectorConfig(feed_url=FEED_URL))

    result = connector.fetch_since("2026-09-18T09:00:00+00:00")

    assert [item.url for item in result.items] == [SECOND_URL]
    assert result.next_cursor == "2026-09-20T11:30:00+00:00"


@respx.mock
def test_fetch_since_no_new_entries_keeps_cursor() -> None:
    _mock_feed_and_articles()
    connector = RSSConnector(RSSConnectorConfig(feed_url=FEED_URL))

    result = connector.fetch_since("2026-09-20T11:30:00+00:00")

    assert result.items == []
    assert result.next_cursor == "2026-09-20T11:30:00+00:00"
