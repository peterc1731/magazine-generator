from pathlib import Path

import pytest

from app.config import get_settings
from pipeline.storage import load_cleaned_html, save_cleaned_html, save_cover_image


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_save_and_load_cleaned_html_roundtrip() -> None:
    ref = save_cleaned_html("article-123", "<p>Hello world</p>")

    assert Path(ref).exists()
    assert load_cleaned_html(ref) == "<p>Hello world</p>"


def test_save_cleaned_html_creates_parent_directories(tmp_path: Path) -> None:
    save_cleaned_html("article-456", "<p>content</p>")

    assert (tmp_path / "articles" / "article-456.html").exists()


def test_save_cover_image_roundtrip(tmp_path: Path) -> None:
    ref = save_cover_image("issue-789", b"fake-jpeg-bytes")

    assert Path(ref).exists()
    assert Path(ref).read_bytes() == b"fake-jpeg-bytes"
    assert (tmp_path / "covers" / "issue-789.jpg").exists()
