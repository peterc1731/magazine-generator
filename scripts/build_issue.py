"""Phase 2 end-to-end slice: Guardian API -> ePub, no DB persistence yet.

Proves the connector -> ePub builder path produces a real, readable .epub
before the orchestration/classification/other-connectors work in later
phases. Requires GUARDIAN_API_KEY in the environment or .env.

Usage: uv run python scripts/build_issue.py [--section technology] [--days 7]
"""

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.config import get_settings
from connectors.guardian import GuardianAPIConfig, GuardianAPIConnector
from pipeline.epub_builder import EpubArticleInput, build_epub


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--section", default=None, help="Guardian section to filter by")
    parser.add_argument("--days", type=int, default=7, help="How far back to look on a first run")
    parser.add_argument("--output", default=None, help="Output .epub path")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.guardian_api_key:
        raise SystemExit("GUARDIAN_API_KEY is not set — add it to .env")

    connector = GuardianAPIConnector(
        GuardianAPIConfig(api_key=settings.guardian_api_key, section=args.section)
    )
    cursor = (datetime.now(UTC) - timedelta(days=args.days)).isoformat()
    result = connector.fetch_since(cursor)

    if not result.items:
        print("No articles found in that window.")
        return

    articles = [
        EpubArticleInput(
            title=item.title,
            source_name="The Guardian",
            html_body=item.cleaned_html or "",
            author=item.author,
            published_at=item.published_at,
        )
        for item in result.items
    ]

    issue_date = datetime.now(UTC).date().isoformat()
    output_path = Path(args.output or f"output/issue-{issue_date}.epub")
    build_epub(articles, issue_title=f"Magazine — {issue_date}", output_path=output_path)

    print(f"Built {output_path} with {len(articles)} article(s).")


if __name__ == "__main__":
    main()
