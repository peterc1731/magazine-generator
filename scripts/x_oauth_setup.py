"""One-time interactive OAuth 2.0 + PKCE setup for the X bookmarks connector.

Run once you have X API credits set up and an OAuth 2.0 app registered at
https://developer.x.com/ (redirect URI must match REDIRECT_URI below —
register it as e.g. http://127.0.0.1:8080/callback). Prints the values to
copy into .env (X_ACCESS_TOKEN, X_REFRESH_TOKEN, X_USER_ID).

Usage: uv run python scripts/x_oauth_setup.py
"""

import secrets
from urllib.parse import parse_qs, urlsplit

import httpx

from app.config import get_settings
from connectors.x_oauth import build_authorize_url, exchange_code_for_tokens, generate_pkce_pair

REDIRECT_URI = "http://127.0.0.1:8080/callback"


def main() -> None:
    settings = get_settings()
    if not settings.x_client_id:
        raise SystemExit("X_CLIENT_ID is not set — add it to .env first")

    verifier, challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(16)
    authorize_url = build_authorize_url(
        client_id=settings.x_client_id,
        redirect_uri=REDIRECT_URI,
        state=state,
        code_challenge=challenge,
    )

    print("1. Open this URL in a browser and authorize the app:\n")
    print(f"   {authorize_url}\n")
    print(f"2. You'll land on a page that fails to load at {REDIRECT_URI}/...")
    print("   That's expected — nothing is listening there. Copy the FULL URL")
    print("   from your browser's address bar and paste it below.\n")

    callback_url = input("Paste the redirect URL here: ").strip()
    query = parse_qs(urlsplit(callback_url).query)

    if query.get("state", [None])[0] != state:
        raise SystemExit("State mismatch — possible CSRF, aborting. Try again.")
    code = query.get("code", [None])[0]
    if not code:
        raise SystemExit(f"No 'code' param found in that URL: {callback_url}")

    with httpx.Client(timeout=10.0) as client:
        tokens = exchange_code_for_tokens(
            client,
            client_id=settings.x_client_id,
            redirect_uri=REDIRECT_URI,
            code=code,
            code_verifier=verifier,
            client_secret=settings.x_client_secret or None,
        )
        me = client.get(
            "https://api.x.com/2/users/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        me.raise_for_status()
        user_id = me.json()["data"]["id"]

    print("\nSuccess. Add these to .env:\n")
    print(f"X_ACCESS_TOKEN={tokens['access_token']}")
    print(f"X_REFRESH_TOKEN={tokens.get('refresh_token', '')}")
    print(f"X_USER_ID={user_id}")


if __name__ == "__main__":
    main()
