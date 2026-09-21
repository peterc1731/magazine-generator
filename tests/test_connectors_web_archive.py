from pathlib import Path

import httpx
import respx

from connectors.web_archive import WebArchiveConnector, WebArchiveConnectorConfig

FIXTURES = Path(__file__).parent / "fixtures" / "html"
ARCHIVE_URL = "https://www.densediscovery.com/issues/"
ISSUE_003 = "https://www.densediscovery.com/issues/003-widgets"
ISSUE_002 = "https://www.densediscovery.com/issues/002-gadgets"
ISSUE_001 = "https://www.densediscovery.com/issues/001-launch"

ISSUE_TEMPLATE = (FIXTURES / "newsletter_issue.html").read_text()


def _issue_html(number: str, title: str) -> str:
    return ISSUE_TEMPLATE.format(issue_number=number, issue_title=title, body="Some links here.")


def _mock_archive_and_issues() -> None:
    respx.get(ARCHIVE_URL).mock(
        return_value=httpx.Response(200, text=(FIXTURES / "archive_index.html").read_text())
    )
    respx.get(ISSUE_003).mock(
        return_value=httpx.Response(200, text=_issue_html("003", "Widgets Everywhere"))
    )
    respx.get(ISSUE_002).mock(
        return_value=httpx.Response(200, text=_issue_html("002", "Gadget Roundup"))
    )
    respx.get(ISSUE_001).mock(
        return_value=httpx.Response(200, text=_issue_html("001", "Launch Issue"))
    )


@respx.mock
def test_first_fetch_limits_to_most_recent_issues_in_chronological_order() -> None:
    _mock_archive_and_issues()
    connector = WebArchiveConnector(
        WebArchiveConnectorConfig(
            archive_url=ARCHIVE_URL, link_selector="a.issue-link", initial_fetch_limit=2
        )
    )

    result = connector.fetch_since(None)

    assert [item.url for item in result.items] == [ISSUE_002, ISSUE_003]
    assert "Issue #002" in result.items[0].title
    assert result.next_cursor == ISSUE_003


@respx.mock
def test_fetch_since_cursor_returns_only_newer_issues() -> None:
    _mock_archive_and_issues()
    connector = WebArchiveConnector(
        WebArchiveConnectorConfig(archive_url=ARCHIVE_URL, link_selector="a.issue-link")
    )

    result = connector.fetch_since(ISSUE_002)

    assert [item.url for item in result.items] == [ISSUE_003]
    assert result.next_cursor == ISSUE_003


@respx.mock
def test_fetch_since_newest_cursor_returns_nothing() -> None:
    _mock_archive_and_issues()
    connector = WebArchiveConnector(
        WebArchiveConnectorConfig(archive_url=ARCHIVE_URL, link_selector="a.issue-link")
    )

    result = connector.fetch_since(ISSUE_003)

    assert result.items == []
    assert result.next_cursor == ISSUE_003
