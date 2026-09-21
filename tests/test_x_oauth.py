import base64
import hashlib

import httpx
import respx

from connectors.x_oauth import (
    TOKEN_URL,
    build_authorize_url,
    exchange_code_for_tokens,
    generate_pkce_pair,
    refresh_access_token,
)


def test_generate_pkce_pair_challenge_matches_verifier() -> None:
    verifier, challenge = generate_pkce_pair()

    expected_digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected_challenge = base64.urlsafe_b64encode(expected_digest).rstrip(b"=").decode("ascii")

    assert challenge == expected_challenge
    assert "=" not in verifier
    assert "=" not in challenge


def test_build_authorize_url_includes_required_params() -> None:
    url = build_authorize_url(
        client_id="client-1",
        redirect_uri="https://localhost/callback",
        state="state-123",
        code_challenge="challenge-abc",
    )

    assert url.startswith("https://x.com/i/oauth2/authorize?")
    assert "client_id=client-1" in url
    assert "code_challenge=challenge-abc" in url
    assert "code_challenge_method=S256" in url
    assert "state=state-123" in url
    assert "bookmark.read" in url
    assert "offline.access" in url


@respx.mock
def test_exchange_code_for_tokens_posts_expected_form_data() -> None:
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "a", "refresh_token": "b"})
    )

    with httpx.Client() as client:
        result = exchange_code_for_tokens(
            client,
            client_id="client-1",
            redirect_uri="https://localhost/callback",
            code="auth-code",
            code_verifier="verifier-value",
        )

    assert result == {"access_token": "a", "refresh_token": "b"}
    sent = route.calls[0].request.read().decode()
    assert "grant_type=authorization_code" in sent
    assert "code=auth-code" in sent
    assert "code_verifier=verifier-value" in sent


@respx.mock
def test_refresh_access_token_posts_refresh_grant() -> None:
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "new-a"})
    )

    with httpx.Client() as client:
        result = refresh_access_token(client, client_id="client-1", refresh_token="old-refresh")

    assert result == {"access_token": "new-a"}
    sent = route.calls[0].request.read().decode()
    assert "grant_type=refresh_token" in sent
    assert "refresh_token=old-refresh" in sent
