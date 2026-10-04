import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Source, SourceType
from connectors.guardian import GuardianAPIConnector
from connectors.rss import RSSConnector
from connectors.web_archive import WebArchiveConnector
from connectors.x_bookmarks import XBookmarksConnector
from pipeline.connector_factory import build_connector
from pipeline.settings_store import get_x_tokens, set_x_tokens


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_build_connector_guardian_injects_api_key_from_settings() -> None:
    source = Source(name="The Guardian", type=SourceType.GUARDIAN_API, config={"section": "world"})
    settings = _settings(guardian_api_key="secret-key")

    connector = build_connector(source, settings)

    assert isinstance(connector, GuardianAPIConnector)
    assert connector._config.api_key == "secret-key"
    assert connector._config.section == "world"


def test_build_connector_rss_uses_source_config_only() -> None:
    source = Source(
        name="BBC News", type=SourceType.RSS, config={"feed_url": "https://bbc.co.uk/rss"}
    )

    connector = build_connector(source, _settings())

    assert isinstance(connector, RSSConnector)
    assert connector._config.feed_url == "https://bbc.co.uk/rss"


def test_build_connector_web_archive() -> None:
    source = Source(
        name="Dense Discovery",
        type=SourceType.WEB_ARCHIVE,
        config={"archive_url": "https://example.com/issues/", "link_selector": "a.issue"},
    )

    connector = build_connector(source, _settings())

    assert isinstance(connector, WebArchiveConnector)


def test_build_connector_x_bookmarks_pulls_credentials_from_settings() -> None:
    source = Source(name="X Bookmarks", type=SourceType.X_BOOKMARKS, config={})
    settings = _settings(
        x_user_id="123", x_access_token="token", x_client_id="client", x_refresh_token="refresh"
    )

    connector = build_connector(source, settings)

    assert isinstance(connector, XBookmarksConnector)
    assert connector._config.user_id == "123"
    assert connector._config.access_token == "token"


def test_build_connector_x_bookmarks_without_access_token_raises() -> None:
    source = Source(name="X Bookmarks", type=SourceType.X_BOOKMARKS, config={})

    with pytest.raises(ValueError, match="not configured"):
        build_connector(source, _settings())


def _x_settings() -> Settings:
    return _settings(
        x_user_id="123",
        x_access_token="env-access",
        x_client_id="client",
        x_refresh_token="env-refresh",
    )


def test_build_connector_x_bookmarks_uses_tokens_stored_in_db(db_session: Session) -> None:
    source = Source(name="X Bookmarks", type=SourceType.X_BOOKMARKS, config={})
    set_x_tokens(db_session, "db-access", "db-refresh", env_refresh_token="env-refresh")

    connector = build_connector(source, _x_settings(), db_session)

    assert connector._config.access_token == "db-access"
    assert connector._config.refresh_token == "db-refresh"


def test_build_connector_x_bookmarks_persists_refreshed_tokens(db_session: Session) -> None:
    source = Source(name="X Bookmarks", type=SourceType.X_BOOKMARKS, config={})

    connector = build_connector(source, _x_settings(), db_session)
    connector._config.on_tokens_refreshed("rotated-access", "rotated-refresh")

    tokens = get_x_tokens(db_session, "env-access", "env-refresh")
    assert tokens == ("rotated-access", "rotated-refresh")
