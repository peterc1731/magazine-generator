from app.config import Settings
from app.models import Source, SourceType
from connectors.base import SourceConnector
from connectors.guardian import GuardianAPIConfig, GuardianAPIConnector
from connectors.rss import RSSConnector, RSSConnectorConfig
from connectors.web_archive import WebArchiveConnector, WebArchiveConnectorConfig
from connectors.x_bookmarks import XBookmarksConfig, XBookmarksConnector


def build_connector(source: Source, settings: Settings) -> SourceConnector:
    """Builds the right connector for a `Source` row.

    Account-level secrets (API keys, OAuth tokens) come from `settings`, not
    `source.config` — those are shared across the account, not per-source,
    and shouldn't be duplicated into a row a future web UI might expose.
    `source.config` supplies only the source's own behavioral config (feed
    URL, section, archive URL/selector, ...).
    """
    if source.type == SourceType.GUARDIAN_API:
        return GuardianAPIConnector(
            GuardianAPIConfig(api_key=settings.guardian_api_key, **source.config)
        )
    if source.type == SourceType.RSS:
        return RSSConnector(RSSConnectorConfig(**source.config))
    if source.type == SourceType.WEB_ARCHIVE:
        return WebArchiveConnector(WebArchiveConnectorConfig(**source.config))
    if source.type == SourceType.X_BOOKMARKS:
        if not settings.x_access_token:
            raise ValueError(
                "X bookmarks source is not configured (no X_ACCESS_TOKEN) "
                "— run scripts/x_oauth_setup.py"
            )
        return XBookmarksConnector(
            XBookmarksConfig(
                user_id=settings.x_user_id,
                access_token=settings.x_access_token,
                client_id=settings.x_client_id,
                client_secret=settings.x_client_secret or None,
                refresh_token=settings.x_refresh_token or None,
            )
        )
    raise ValueError(f"Unknown source type: {source.type}")
