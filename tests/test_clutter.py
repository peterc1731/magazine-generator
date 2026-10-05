import pytest
from bs4 import BeautifulSoup

from pipeline.clutter import is_social_icon, remove_empty_containers, strip_clutter


def _clean(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    strip_clutter(soup)
    remove_empty_containers(soup)
    return str(soup)


def _img(src: str, alt: str = "") -> object:
    return BeautifulSoup(f'<img src="{src}" alt="{alt}">', "html.parser").img


def test_share_button_row_is_removed() -> None:
    html = (
        "<p>Bottom line: a bad cook.</p><p>"
        '<a href="https://www.facebook.com/sharer/sharer.php?u=x"><img src="https://bytes.dev/i/fb.png"></a>'
        '<a href="https://www.linkedin.com/sharing/share-offsite/?url=x"><img src="https://bytes.dev/i/a.png"></a>'
        '<a href="https://twitter.com/intent/tweet?text=x"><img src="https://bytes.dev/i/b.png"></a>'
        '<a href="mailto:?subject=Bytes"><img src="https://bytes.dev/i/c.png"></a>'
        "</p>"
    )

    assert _clean(html) == "<p>Bottom line: a bad cook.</p>"


@pytest.mark.parametrize(
    ("src", "alt"),
    [
        ("https://bytes.dev/images/facebook.png", ""),
        ("https://bytes.dev/images/linkedin-icon@2x.png", ""),
        ("https://bytes.dev/images/twitter_logo_white.svg", ""),
        ("https://cdn.example.com/email-icon.4f9a2b7c.png", ""),
        ("https://bytes.dev/_next/image?url=%2Ficons%2Fx-logo.png&w=64&q=75", ""),
        ("https://bytes.dev/a.png", "Twitter"),
        ("https://bytes.dev/b.png", "Share on LinkedIn"),
        ("https://bytes.dev/c.png", "email"),
    ],
)
def test_social_icons_are_recognised(src: str, alt: str) -> None:
    assert is_social_icon(_img(src, alt))


@pytest.mark.parametrize(
    ("src", "alt"),
    [
        ("https://media.guim.co.uk/zuckerberg-facebook-hearing.jpg", ""),
        ("https://media.guim.co.uk/1200.jpg", "Mark Zuckerberg at the Facebook hearing"),
        ("https://bytes.dev/images/chart.png", "Downloads per week"),
        ("https://www.densediscovery.com/archive/408/book1.jpg", "IMG"),
    ],
)
def test_article_images_are_not_mistaken_for_icons(src: str, alt: str) -> None:
    assert not is_social_icon(_img(src, alt))


def test_plain_text_links_to_social_sites_are_kept() -> None:
    html = '<p>Read the <a href="https://twitter.com/someone/status/1">thread</a>.</p>'

    assert _clean(html) == html


def test_embedded_media_and_emptied_figures_are_removed() -> None:
    html = (
        "<p>Intro</p>"
        '<figure class="element-video"><iframe src="https://www.youtube.com/embed/x"></iframe>'
        "<figcaption>Watch the trailer</figcaption></figure>"
        '<video controls><source src="clip.mp4"></video>'
        '<figure><img src="https://example.com/photo.jpg"><figcaption>Kept</figcaption></figure>'
    )

    cleaned = _clean(html)

    assert "iframe" not in cleaned
    assert "video" not in cleaned
    assert "Watch the trailer" not in cleaned
    assert "photo.jpg" in cleaned
    assert "Kept" in cleaned
