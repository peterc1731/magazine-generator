from pathlib import Path

import httpx
import pytest
import respx

from connectors.web_archive import (
    MAX_NEW_ISSUES_PER_RUN,
    WebArchiveConnector,
    WebArchiveConnectorConfig,
)

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


# --- Numbered mode -------------------------------------------------------------

NUMBERED_TEMPLATE = "https://www.densediscovery.com/archive/{number}/"
NUMBERED_PATTERN = r"^https://www\.densediscovery\.com/archive/(?P<number>\d+)/$"


def _mock_numbered_site(latest: int) -> respx.Route:
    """Issues 1..latest exist; anything higher is a 404."""

    def respond(request: httpx.Request, number: str) -> httpx.Response:
        if 1 <= int(number) <= latest:
            return httpx.Response(200, text=_issue_html(number, f"Issue {number}"))
        return httpx.Response(404)

    return respx.get(url__regex=NUMBERED_PATTERN).mock(side_effect=respond)


def _numbered_connector(**overrides) -> WebArchiveConnector:
    config = WebArchiveConnectorConfig(issue_url_template=NUMBERED_TEMPLATE, **overrides)
    return WebArchiveConnector(config)


@respx.mock
def test_numbered_first_fetch_finds_latest_issue_and_takes_most_recent() -> None:
    route = _mock_numbered_site(latest=408)

    result = _numbered_connector(initial_fetch_limit=3).fetch_since(None)

    assert [item.url for item in result.items] == [
        NUMBERED_TEMPLATE.format(number=n) for n in (406, 407, 408)
    ]
    assert result.next_cursor == "408"
    # Found by doubling + binary search, not by walking all 408 issues.
    assert route.call_count < 40


@respx.mock
def test_numbered_fetch_since_cursor_returns_only_newer_issues() -> None:
    _mock_numbered_site(latest=410)

    result = _numbered_connector().fetch_since("408")

    assert [item.url for item in result.items] == [
        NUMBERED_TEMPLATE.format(number=n) for n in (409, 410)
    ]
    assert result.next_cursor == "410"


@respx.mock
def test_numbered_fetch_with_nothing_new_keeps_cursor() -> None:
    _mock_numbered_site(latest=408)

    result = _numbered_connector().fetch_since("408")

    assert result.items == []
    assert result.next_cursor == "408"


@respx.mock
def test_numbered_fetch_treats_redirect_away_as_missing_issue() -> None:
    respx.get(NUMBERED_TEMPLATE.format(number=409)).mock(
        return_value=httpx.Response(200, text=_issue_html("409", "Issue 409"))
    )
    respx.get(NUMBERED_TEMPLATE.format(number=410)).mock(
        return_value=httpx.Response(302, headers={"Location": "https://www.densediscovery.com/"})
    )
    respx.get("https://www.densediscovery.com/").mock(
        return_value=httpx.Response(200, text="<html>home</html>")
    )
    connector = WebArchiveConnector(
        WebArchiveConnectorConfig(issue_url_template=NUMBERED_TEMPLATE),
        client=httpx.Client(follow_redirects=True),
    )

    result = connector.fetch_since("408")

    assert [item.url for item in result.items] == [NUMBERED_TEMPLATE.format(number=409)]
    assert result.next_cursor == "409"


@respx.mock
def test_numbered_fetch_caps_new_issues_per_run() -> None:
    _mock_numbered_site(latest=10_000)

    result = _numbered_connector().fetch_since("100")

    assert len(result.items) == MAX_NEW_ISSUES_PER_RUN
    assert result.next_cursor == str(100 + MAX_NEW_ISSUES_PER_RUN)


@respx.mock
def test_numbered_first_fetch_errors_when_every_number_exists() -> None:
    respx.get(url__regex=NUMBERED_PATTERN).mock(
        return_value=httpx.Response(200, text=_issue_html("1", "Soft 404"))
    )

    with pytest.raises(ValueError, match="answers 200 for missing issues"):
        _numbered_connector().fetch_since(None)
