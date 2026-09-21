from pathlib import Path

from pipeline.extraction import extract_article

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
