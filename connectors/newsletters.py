"""Site-specific WebArchiveConnector configs for the two newsletters in
PRD.md §6 (Dense Discovery, bytes.dev) — neither publishes RSS.

Dense Discovery: the archive page builds its issue list with JavaScript
(clicks load each issue into an iframe), so there are no links for a
selector to find. Each issue does have its own numbered URL, though
(confirmed by the user: /archive/408/), so it uses numbered mode instead.

bytes.dev: archive URL and link selector are still a best guess, NOT
verified against the live markup (this environment's egress proxy blocks
the domain) — check it with "Test fetch" in the sources UI.
"""

from connectors.web_archive import WebArchiveConnectorConfig

# Sponsor slot, classified ads (+ their "book yours here" note), the
# share/support footer, and the site logos.
DENSE_DISCOVERY_REMOVE_SELECTORS = [
    '[data-category="spo"]',
    '[data-category="cla"]',
    'p:-soup-contains("Classifieds are paid ads")',
    "table.footer",
    'img[alt="Dense Discovery"]',
]

DENSE_DISCOVERY_CONFIG = WebArchiveConnectorConfig(
    issue_url_template="https://www.densediscovery.com/archive/{number}/",
    # Issues are email-template HTML (nested layout tables) — see
    # tests/fixtures/html/dense_discovery_408.html.
    content_mode="newsletter",
    remove_selectors=DENSE_DISCOVERY_REMOVE_SELECTORS,
)

BYTES_DEV_CONFIG = WebArchiveConnectorConfig(
    archive_url="https://bytes.dev/archives",
    link_selector="a[href^='/archives/']",
)
