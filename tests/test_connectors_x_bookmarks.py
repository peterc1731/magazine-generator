import httpx
import respx

from connectors.x_bookmarks import BOOKMARKS_URL_TEMPLATE, XBookmarksConfig, XBookmarksConnector
from connectors.x_oauth import TOKEN_URL

BOOKMARKS_URL = BOOKMARKS_URL_TEMPLATE.format(user_id="123")


def _tweet(tweet_id: str, text: str, created_at: str) -> dict:
    return {"id": tweet_id, "text": text, "created_at": created_at}


@respx.mock
def test_fetch_since_none_single_page_returns_chronological_order() -> None:
    respx.get(BOOKMARKS_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    _tweet("300", "Newest bookmark", "2026-09-20T10:00:00Z"),
                    _tweet("200", "Middle bookmark", "2026-09-18T10:00:00Z"),
                ],
                "meta": {},
            },
        )
    )
    connector = XBookmarksConnector(
        XBookmarksConfig(user_id="123", access_token="token-1", client_id="client-1")
    )

    result = connector.fetch_since(None)

    assert [item.source_item_id for item in result.items] == ["200", "300"]
    assert result.items[1].title == "Newest bookmark"
    assert result.next_cursor == "300"


@respx.mock
def test_fetch_since_cursor_stops_at_last_seen_bookmark() -> None:
    respx.get(BOOKMARKS_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    _tweet("300", "Newest bookmark", "2026-09-20T10:00:00Z"),
                    _tweet("200", "Already seen", "2026-09-18T10:00:00Z"),
                ],
                "meta": {},
            },
        )
    )
    connector = XBookmarksConnector(
        XBookmarksConfig(user_id="123", access_token="token-1", client_id="client-1")
    )

    result = connector.fetch_since("200")

    assert [item.source_item_id for item in result.items] == ["300"]
    assert result.next_cursor == "300"


@respx.mock
def test_fetch_since_pages_forward_when_cursor_not_on_first_page() -> None:
    route = respx.get(BOOKMARKS_URL)
    route.side_effect = [
        httpx.Response(
            200,
            json={
                "data": [_tweet("300", "Page 1 item", "2026-09-20T10:00:00Z")],
                "meta": {"next_token": "page-2"},
            },
        ),
        httpx.Response(
            200,
            json={
                "data": [_tweet("200", "Page 2 item", "2026-09-18T10:00:00Z")],
                "meta": {},
            },
        ),
    ]
    connector = XBookmarksConnector(
        XBookmarksConfig(user_id="123", access_token="token-1", client_id="client-1")
    )

    result = connector.fetch_since(None)

    assert [item.source_item_id for item in result.items] == ["200", "300"]
    assert result.next_cursor == "300"


@respx.mock
def test_expired_access_token_is_refreshed_and_retried() -> None:
    bookmarks_route = respx.get(BOOKMARKS_URL)
    bookmarks_route.side_effect = [
        httpx.Response(401, json={"title": "Unauthorized"}),
        httpx.Response(
            200,
            json={"data": [_tweet("300", "After refresh", "2026-09-20T10:00:00Z")], "meta": {}},
        ),
    ]
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "new-token", "refresh_token": "new-refresh"}
        )
    )
    connector = XBookmarksConnector(
        XBookmarksConfig(
            user_id="123",
            access_token="expired-token",
            client_id="client-1",
            refresh_token="old-refresh",
        )
    )

    result = connector.fetch_since(None)

    assert [item.source_item_id for item in result.items] == ["300"]
    assert bookmarks_route.calls[1].request.headers["Authorization"] == "Bearer new-token"
