"""Site-specific WebArchiveConnector configs for the two newsletters in
PRD.md §6 (Dense Discovery, bytes.dev) — neither publishes RSS.

The archive URL and link selector below are best-guesses based on how these
sites are known to be structured, NOT yet verified against the live markup
(this environment's egress proxy blocks both domains). Confirming/adjusting
these against the real page is the remaining open item from
ARCHITECTURE.md §5.3 / TASKS.md Phase 3 — do that before relying on these
in a real run.
"""

from connectors.web_archive import WebArchiveConnectorConfig

DENSE_DISCOVERY_CONFIG = WebArchiveConnectorConfig(
    archive_url="https://www.densediscovery.com/issues/",
    link_selector="a[href^='/issues/']",
)

BYTES_DEV_CONFIG = WebArchiveConnectorConfig(
    archive_url="https://bytes.dev/archives",
    link_selector="a[href^='/archives/']",
)
