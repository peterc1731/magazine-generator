from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

CLASSIFICATION_MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = """You are helping curate a personal weekly reading digest.
Given the reader's stated interests and a batch of candidate articles, score
each article's relevance to those interests, assign it a section, and flag
duplicate coverage.

Respond with ONLY a JSON array (no prose, no markdown fences), one object per
article, in this exact shape:
[{"id": "<id>", "relevance_score": <0-10 number>, "section": "<short section name>",
  "duplicate_of": "<id or null>"}]

Score higher for topics closely matching the reader's stated interests, lower
for tangential or unrelated topics. Keep section names short and consistent
across articles in the same batch (e.g. "Tech", "World News", "Culture").

Articles are listed in source-preference order. When two or more articles in
this batch cover the same underlying story (e.g. the same news event reported
by different outlets), set "duplicate_of" on every LATER one to the "id" of
the FIRST one in the list covering that story, so only the earliest is kept.
Set "duplicate_of" to null for anything that isn't a duplicate of an earlier
article in this batch."""


@dataclass
class ClassificationInput:
    id: str
    title: str
    summary: str


@dataclass
class ClassificationResult:
    id: str
    relevance_score: float
    section: str
    duplicate_of: str | None = None


class _MessagesClient(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class _AnthropicClient(Protocol):
    messages: _MessagesClient


def classify_articles(
    client: _AnthropicClient,
    interest_profile: str,
    articles: list[ClassificationInput],
    model: str = CLASSIFICATION_MODEL,
) -> list[ClassificationResult]:
    """Batches all articles into a single Claude call for relevance scoring,
    section tagging, and duplicate-story detection (ARCHITECTURE.md §3.5).
    One call per run's worth of candidates, not one per article, to keep
    token cost down — this also means dedup piggybacks on a call already
    being made rather than needing a separate embeddings step/provider.

    `articles` should be ordered by source preference: when the model finds
    two articles covering the same story, it's told to flag the later one as
    a duplicate of the earlier one, so put your preferred sources first.
    """
    if not articles:
        return []

    response = client.messages.create(
        model=model,
        max_tokens=1024 + 256 * len(articles),
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_message(interest_profile, articles)}],
    )

    text = "".join(block.text for block in response.content if block.type == "text")
    return _parse_response(text, expected_ids={article.id for article in articles})


def _build_user_message(interest_profile: str, articles: list[ClassificationInput]) -> str:
    lines = [f"Reader's interests:\n{interest_profile or '(none specified)'}\n", "Articles:"]
    for article in articles:
        lines.append(f"- id: {article.id}\n  title: {article.title}\n  summary: {article.summary}")
    return "\n".join(lines)


def _parse_response(text: str, expected_ids: set[str]) -> list[ClassificationResult]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]

    data = json.loads(text)

    results = []
    for entry in data:
        entry_id = entry.get("id")
        if entry_id not in expected_ids:
            continue
        duplicate_of = entry.get("duplicate_of")
        if duplicate_of not in expected_ids or duplicate_of == entry_id:
            duplicate_of = None
        results.append(
            ClassificationResult(
                id=entry_id,
                relevance_score=float(entry["relevance_score"]),
                section=entry.get("section") or "Uncategorized",
                duplicate_of=duplicate_of,
            )
        )
    return results
