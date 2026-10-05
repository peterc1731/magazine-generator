"""Removes non-article clutter from chapter HTML before it goes into the
epub: social share buttons, embedded media (an offline e-reader can't
play it) and the empty wrappers they leave behind. Applied to every
source by the epub builder."""

import re
from urllib.parse import parse_qs, unquote, urlsplit

from bs4 import BeautifulSoup, Tag

# Embeds an e-reader can't play — at best they render as blank boxes.
_MEDIA_TAGS = ("iframe", "video", "audio", "embed", "object", "source", "track")

# Links that exist only to share the article, e.g. a row of icon buttons.
_SHARE_LINK = re.compile(
    r"(facebook\.com/(sharer|share\.php|dialog/share)"
    r"|linkedin\.com/(shareArticle|sharing/share-offsite|cws/share)"
    r"|(twitter|x)\.com/(intent/(tweet|post)|share)"
    r"|reddit\.com/submit|news\.ycombinator\.com/submitlink"
    r"|wa\.me/|api\.whatsapp\.com/send|t\.me/share|bsky\.app/intent"
    r"|threads\.net/intent|pinterest\.com/pin/create|^mailto:\?)",
    re.IGNORECASE,
)

_SOCIAL_NAMES = {
    "facebook", "fb", "linkedin", "twitter", "x", "email", "mail", "envelope",
    "whatsapp", "reddit", "threads", "bluesky", "bsky", "mastodon", "instagram",
    "telegram", "pinterest", "hackernews", "hn", "share", "rss",
}  # fmt: skip
# Words that can sit alongside a social name in an icon's file name.
_ICON_WORDS = {
    "icon", "icons", "logo", "share", "social", "btn", "button", "white", "black",
    "color", "colour", "circle", "square", "round", "rounded", "sm", "small", "mono",
    "outline", "filled", "solid", "dark", "light", "badge", "symbol",
}  # fmt: skip
_IGNORABLE_TOKEN = re.compile(r"^(\d+x?\d*|[0-9a-f]{6,}|\d+px|v\d+|@\dx)$", re.IGNORECASE)


def strip_clutter(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(_MEDIA_TAGS):
        tag.decompose()
    for link in soup.find_all("a", href=True):
        if _SHARE_LINK.search(link["href"]):
            link.decompose()
    for img in soup.find_all("img"):
        if is_social_icon(img):
            img.decompose()


def is_social_icon(img: Tag) -> bool:
    """A share/follow button image: its alt text or file name is just a
    social network's name (plus words like "icon"/"logo"). Article photos
    that merely mention one ("zuckerberg-facebook-hearing.jpg", "Mark
    Zuckerberg at the Facebook hearing") don't match."""
    alt = " ".join((img.get("alt") or "").lower().split())
    alt = re.sub(r"^(share|follow us|follow)( (on|via|by))? ", "", alt)
    if alt and _only_social_words(re.split(r"[\s/|-]+", alt)):
        return True
    return any(_only_social_words(re.split(r"[^a-z0-9]+", name)) for name in _file_names(img))


def _file_names(img: Tag) -> list[str]:
    src = img.get("src") or ""
    parts = urlsplit(src)
    names = [parts.path.rsplit("/", 1)[-1]]
    # Image CDNs/optimizers wrap the real path in a query parameter, e.g.
    # /_next/image?url=%2Ficons%2Flinkedin.png&w=64
    for values in parse_qs(parts.query).values():
        names += [unquote(value).rsplit("/", 1)[-1] for value in values if "/" in unquote(value)]
    return [name.lower().rsplit(".", 1)[0] for name in names if name]


def _only_social_words(tokens: list[str]) -> bool:
    words = [token for token in tokens if token and not _IGNORABLE_TOKEN.match(token)]
    return (
        bool(words)
        and any(word in _SOCIAL_NAMES for word in words)
        and all(word in _SOCIAL_NAMES or word in _ICON_WORDS for word in words)
    )


def remove_empty_containers(soup: BeautifulSoup) -> None:
    """Drops wrappers emptied by the removals above — a link or paragraph
    that held only an icon, a figure left with just its caption."""
    for figure in soup.find_all("figure"):
        if not figure.find("img"):
            figure.decompose()
    changed = True
    while changed:
        changed = False
        for tag in soup.find_all(["a", "p", "li", "ul", "ol", "div", "span", "picture"]):
            if tag.decomposed:
                continue
            if not tag.get_text(strip=True) and not tag.find(["img", "br"]):
                tag.decompose()
                changed = True
