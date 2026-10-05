import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import respx

from connectors.guardian import (
    GUARDIAN_API_BASE,
    GuardianAPIConfig,
    GuardianAPIConnector,
    _strip_promos,
)

FIXTURE = Path(__file__).parent / "fixtures" / "guardian" / "search_response.json"


@respx.mock
def test_fetch_since_none_returns_all_items_and_latest_cursor() -> None:
    respx.get(GUARDIAN_API_BASE).mock(
        return_value=httpx.Response(200, json=json.loads(FIXTURE.read_text()))
    )
    connector = GuardianAPIConnector(GuardianAPIConfig(api_key="test-key", section="technology"))

    result = connector.fetch_since(None)

    assert [item.title for item in result.items] == [
        "First example headline",
        "Second example headline",
    ]
    assert result.items[0].author == "Alex Reporter"
    assert result.items[0].cleaned_html == "<p>Body of the first example article.</p>"
    assert result.next_cursor == "2026-09-20T11:30:00+00:00"


@respx.mock
def test_fetch_since_cursor_excludes_items_at_or_before_it() -> None:
    respx.get(GUARDIAN_API_BASE).mock(
        return_value=httpx.Response(200, json=json.loads(FIXTURE.read_text()))
    )
    connector = GuardianAPIConnector(GuardianAPIConfig(api_key="test-key"))

    result = connector.fetch_since("2026-09-18T09:00:00+00:00")

    assert [item.title for item in result.items] == ["Second example headline"]
    assert result.next_cursor == "2026-09-20T11:30:00+00:00"


@respx.mock
def test_fetch_since_no_new_items_keeps_cursor() -> None:
    respx.get(GUARDIAN_API_BASE).mock(
        return_value=httpx.Response(200, json=json.loads(FIXTURE.read_text()))
    )
    connector = GuardianAPIConnector(GuardianAPIConfig(api_key="test-key"))

    result = connector.fetch_since("2026-09-20T11:30:00+00:00")

    assert result.items == []
    assert result.next_cursor == "2026-09-20T11:30:00+00:00"


def _single_result_with(fields: dict) -> dict:
    payload = json.loads(FIXTURE.read_text())
    payload["response"]["results"] = payload["response"]["results"][:1]
    payload["response"]["results"][0]["fields"] = fields
    return payload


@respx.mock
def test_lead_image_from_main_field_is_prepended_to_body() -> None:
    main = '<figure class="element-image"><img src="https://media.guim.co.uk/lead.jpg"></figure>'
    route = respx.get(GUARDIAN_API_BASE).mock(
        return_value=httpx.Response(
            200, json=_single_result_with({"body": "<p>Body</p>", "main": main})
        )
    )
    connector = GuardianAPIConnector(GuardianAPIConfig(api_key="test-key"))

    result = connector.fetch_since(None)

    assert result.items[0].cleaned_html == main + "<p>Body</p>"
    assert "main" in route.calls[0].request.url.params["show-fields"]


@respx.mock
def test_non_image_main_media_is_skipped() -> None:
    main = '<figure class="element-video"><iframe src="https://youtube.com/x"></iframe></figure>'
    respx.get(GUARDIAN_API_BASE).mock(
        return_value=httpx.Response(
            200, json=_single_result_with({"body": "<p>Body</p>", "main": main})
        )
    )
    connector = GuardianAPIConnector(GuardianAPIConfig(api_key="test-key"))

    result = connector.fetch_since(None)

    assert result.items[0].cleaned_html == "<p>Body</p>"


@respx.mock
def test_first_fetch_starts_from_recent_days_not_the_archive_start() -> None:
    route = respx.get(GUARDIAN_API_BASE).mock(
        return_value=httpx.Response(200, json=json.loads(FIXTURE.read_text()))
    )
    connector = GuardianAPIConnector(GuardianAPIConfig(api_key="test-key", initial_days=7))

    connector.fetch_since(None)

    expected = (datetime.now(UTC) - timedelta(days=7)).date().isoformat()
    assert route.calls[0].request.url.params["from-date"] == expected


def test_strip_promos_removes_newsletter_signup_and_related_links() -> None:
    body = (
        "<p>The chief executive will turn down an invitation.</p>"
        '<ul><li><p><strong><a href="https://www.theguardian.com/newsletters">'
        "Sign up for Guardian Australia\u2019s Politics, really newsletter here</a></strong></p>"
        "</li></ul>"
        '<p><strong><a href="https://www.theguardian.com/email">Get our breaking news email'
        "</a></strong></p>"
        '<aside class="element element-rich-link"><p>Related: <a href="/x">Other story</a></p>'
        "</aside>"
        "<p>Neither company could be compelled to appear.</p>"
    )

    cleaned = _strip_promos(body)

    assert "Sign up" not in cleaned
    assert "breaking news email" not in cleaned
    assert "Other story" not in cleaned
    assert "<ul>" not in cleaned  # the list emptied by the removal goes too
    assert "turn down an invitation" in cleaned
    assert "compelled to appear" in cleaned


def test_strip_promos_keeps_prose_that_merely_starts_like_a_promo() -> None:
    body = (
        '<p>Get our view: the <a href="/x">policy</a> was always going to fail, critics say, '
        "because nobody had asked the people it affected what they actually needed, and the "
        "consultation that followed was too little and far too late to change anything.</p>"
        "<p>Sign up for the scheme opened on Monday without any link at all.</p>"
    )

    assert _strip_promos(body) == body
