"""OAuth 2.0 Authorization Code + PKCE flow for the X API (ARCHITECTURE.md
§5.4). X is a public (no client secret) OAuth client, so PKCE is required.

Endpoints/scopes here follow docs.x.com as of the last time it could be
checked in this codebase's development — verify against
https://docs.x.com/x-api/posts/bookmarks/introduction before relying on them
for a real account, since X has changed auth/pricing details before.
"""

from __future__ import annotations

import base64
import hashlib
import secrets

import httpx

AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
SCOPES = ("tweet.read", "users.read", "bookmark.read", "offline.access")


def generate_pkce_pair() -> tuple[str, str]:
    """Returns (code_verifier, code_challenge) per RFC 7636."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorize_url(client_id: str, redirect_uri: str, state: str, code_challenge: str) -> str:
    params = httpx.QueryParams(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(SCOPES),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{AUTHORIZE_URL}?{params}"


def exchange_code_for_tokens(
    client: httpx.Client,
    client_id: str,
    redirect_uri: str,
    code: str,
    code_verifier: str,
    client_secret: str | None = None,
) -> dict[str, str]:
    response = client.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code": code,
            "code_verifier": code_verifier,
        },
        auth=_basic_auth(client_id, client_secret),
    )
    response.raise_for_status()
    return response.json()


def refresh_access_token(
    client: httpx.Client,
    client_id: str,
    refresh_token: str,
    client_secret: str | None = None,
) -> dict[str, str]:
    response = client.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
        },
        auth=_basic_auth(client_id, client_secret),
    )
    response.raise_for_status()
    return response.json()


def _basic_auth(client_id: str, client_secret: str | None) -> httpx.BasicAuth | None:
    """X's "confidential" OAuth app type requires Basic auth with the client
    secret on token requests; "public" (PKCE-only) apps don't set one."""
    return httpx.BasicAuth(client_id, client_secret) if client_secret else None
