from pathlib import Path

from bs4 import BeautifulSoup

from connectors.newsletters import DENSE_DISCOVERY_REMOVE_SELECTORS
from pipeline.extraction import extract_article, extract_newsletter

FIXTURES = Path(__file__).parent / "fixtures" / "html"


def test_extract_article_strips_boilerplate_and_gets_metadata() -> None:
    html = (FIXTURES / "sample_article.html").read_text()

    result = extract_article(html, url="https://example.com/widgets")

    assert result is not None
    assert result.title == "Scientists Discover New Method For Widget Production"
    assert result.author == "Jane Doe"
    assert result.published_at is not None
    assert result.published_at.date().isoformat() == "2026-09-15"

    assert "breakthrough in" in result.plaintext
    for boilerplate in ("BUY NOW", "Subscribe to our newsletter", "Related articles", "Login"):
        assert boilerplate not in result.plaintext
        assert boilerplate not in result.cleaned_html


def test_extract_article_returns_none_for_empty_page() -> None:
    result = extract_article("<html><body></body></html>", url="https://example.com/empty")

    assert result is None


def test_extract_article_keeps_images_with_absolute_urls() -> None:
    paragraphs = "".join(
        f"<p>Paragraph {n} of a long enough article body to be worth extracting, with "
        "plenty of ordinary prose so the extractor treats it as the main content.</p>"
        for n in range(6)
    )
    html = (
        "<html><head><title>Photo story</title></head><body><article><h1>Photo story</h1>"
        f"{paragraphs[:400]}<figure><img src=\"/images/photo.jpg\" alt=\"A photo\"></figure>"
        f"{paragraphs[400:]}</article></body></html>"
    )

    result = extract_article(html, url="https://example.com/stories/photo")

    assert result is not None
    assert 'src="https://example.com/images/photo.jpg"' in result.cleaned_html


# --- Newsletter mode -------------------------------------------------------------

DD_URL = "https://www.densediscovery.com/archive/408/"


def _dense_discovery_408():
    html = (FIXTURES / "dense_discovery_408.html").read_text()
    return extract_newsletter(html, DD_URL, DENSE_DISCOVERY_REMOVE_SELECTORS)


def _headings(cleaned_html: str, level: str) -> list[str]:
    soup = BeautifulSoup(cleaned_html, "html.parser")
    return [" ".join(h.get_text(" ").split()) for h in soup.find_all(level)]


def test_newsletter_keeps_sections_in_order_without_ads() -> None:
    result = _dense_discovery_408()

    assert result is not None
    assert result.title == "Dense Discovery – Issue 408"
    # Section headings (h1 in the email → h2 under the chapter title), in
    # order, minus Sponsor/Classifieds whose content was removed.
    assert _headings(result.cleaned_html, "h2") == [
        "Hello discoverers!",
        "Tools",
        "Wanderings",
        "Books",
        "Socials",
        "Media",
        "Inspiration",
        "Numbers",
        "Socials",
        "Mood",
    ]
    for ad_text in ("boopr", "Persodex", "Classifieds are paid ads", "EmailOctopus"):
        assert ad_text not in result.plaintext


def test_newsletter_keeps_item_titles_next_to_their_section() -> None:
    result = _dense_discovery_408()

    assert result is not None
    titles = _headings(result.cleaned_html, "h3")
    assert titles[:4] == ["Gravity", "Activate Fitness", "Atlas", "Control Panel for YouTube"]
    assert "The opposite of the apocalypse is a neighborhood" in titles
    # Social post attributions are lone headings, but must survive.
    assert "@davidgerard@circumstances.run" in titles
    assert "on Mastodon" in _headings(result.cleaned_html, "h4")
    # Each title is followed by its own description, not by the next title.
    plain = result.plaintext
    gravity, its_description = plain.index("Gravity"), plain.index("append-and-review")
    assert gravity < its_description < plain.index("Activate Fitness")


def test_newsletter_keeps_images_as_absolute_urls_and_drops_logos() -> None:
    result = _dense_discovery_408()

    assert result is not None
    soup = BeautifulSoup(result.cleaned_html, "html.parser")
    sources = [img["src"] for img in soup.find_all("img")]
    assert f"{DD_URL}paint1.jpg" in sources
    assert f"{DD_URL}book1.jpg" in sources
    assert all(src.startswith("https://") for src in sources)
    assert not any("logo" in src for src in sources)
    links = [a["href"] for a in soup.find_all("a")]
    assert "https://www.gravitynotes.app/?ref=DenseDiscovery-408" in links


def test_newsletter_strips_layout_attributes_and_tables() -> None:
    result = _dense_discovery_408()

    assert result is not None
    assert "<table" not in result.cleaned_html
    assert "<td" not in result.cleaned_html
    assert "class=" not in result.cleaned_html
