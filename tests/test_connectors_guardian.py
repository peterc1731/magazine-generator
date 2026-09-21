import json
from pathlib import Path

import httpx
import respx

from connectors.guardian import GUARDIAN_API_BASE, GuardianAPIConfig, GuardianAPIConnector

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
