from pathlib import Path

from app.config import get_settings


def save_cleaned_html(article_id: str, html: str) -> str:
    """Writes cleaned article HTML to local disk and returns the path to
    store as `Article.cleaned_content_ref`. A stand-in for the object-storage
    option in ARCHITECTURE.md §3.8 — fine at this project's scale, and easy
    to swap out behind this same function signature later."""
    path = Path(get_settings().data_dir) / "articles" / f"{article_id}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return str(path)


def load_cleaned_html(ref: str) -> str:
    return Path(ref).read_text(encoding="utf-8")


def save_cover_image(issue_id: str, image_bytes: bytes) -> str:
    """Writes an issue's cover image to local disk and returns the path to
    store as `Issue.cover_ref`, so the OPDS catalog can serve it without
    re-opening the epub file."""
    path = Path(get_settings().data_dir) / "covers" / f"{issue_id}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image_bytes)
    return str(path)
