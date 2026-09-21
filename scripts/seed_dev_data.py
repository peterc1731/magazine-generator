"""Idempotently seed the local dev DB with the sources from docs/PRD.md §6.

Usage: uv run python scripts/seed_dev_data.py
"""

from app.db import SessionLocal, init_db
from app.models import Source, SourceType

SEED_SOURCES = [
    Source(name="The Guardian", type=SourceType.GUARDIAN_API, config={"section": "world"}),
    Source(name="BBC News", type=SourceType.RSS, config={"feed_url": "https://feeds.bbci.co.uk/news/rss.xml"}),
    Source(
        name="Dense Discovery",
        type=SourceType.WEB_ARCHIVE,
        config={"archive_url": "https://www.densediscovery.com/issues/"},
    ),
    Source(name="bytes.dev", type=SourceType.WEB_ARCHIVE, config={"archive_url": "https://bytes.dev/archives"}),
    Source(name="X Bookmarks", type=SourceType.X_BOOKMARKS, config={}),
]


def seed() -> None:
    init_db()
    with SessionLocal() as db:
        existing_names = {name for (name,) in db.query(Source.name).all()}
        added = 0
        for source in SEED_SOURCES:
            if source.name in existing_names:
                continue
            db.add(source)
            added += 1
        db.commit()
    print(f"Seeded {added} new source(s), {len(SEED_SOURCES) - added} already present.")


if __name__ == "__main__":
    seed()
