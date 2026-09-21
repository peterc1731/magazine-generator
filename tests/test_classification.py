import json
from types import SimpleNamespace
from typing import Any

import pytest

from pipeline.classification import ClassificationInput, classify_articles


class FakeMessages:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.response_text)])


class FakeClient:
    def __init__(self, response_text: str) -> None:
        self.messages = FakeMessages(response_text)


def test_classify_articles_returns_empty_for_no_articles() -> None:
    client = FakeClient(response_text="[]")

    result = classify_articles(client, "tech, cycling", articles=[])

    assert result == []
    assert client.messages.calls == []  # no API call made for an empty batch


def test_classify_articles_parses_json_response() -> None:
    payload = json.dumps(
        [
            {"id": "a1", "relevance_score": 8.5, "section": "Tech"},
            {"id": "a2", "relevance_score": 2, "section": "Sports"},
        ]
    )
    client = FakeClient(response_text=payload)
    articles = [
        ClassificationInput(id="a1", title="New AI model released", summary="..."),
        ClassificationInput(id="a2", title="Local football result", summary="..."),
    ]

    results = classify_articles(client, "AI and technology", articles)

    assert results[0].id == "a1"
    assert results[0].relevance_score == 8.5
    assert results[0].section == "Tech"
    assert results[1].relevance_score == 2.0

    sent = client.messages.calls[0]
    assert sent["model"] == "claude-haiku-4-5"
    assert "AI and technology" in sent["messages"][0]["content"]


def test_classify_articles_handles_markdown_fenced_json() -> None:
    body = json.dumps([{"id": "a1", "relevance_score": 5, "section": "Tech"}])
    payload = f"```json\n{body}\n```"
    client = FakeClient(response_text=payload)
    articles = [ClassificationInput(id="a1", title="t", summary="s")]

    results = classify_articles(client, "tech", articles)

    assert len(results) == 1
    assert results[0].id == "a1"


def test_classify_articles_drops_unknown_ids() -> None:
    payload = json.dumps(
        [
            {"id": "a1", "relevance_score": 5, "section": "Tech"},
            {"id": "not-in-batch", "relevance_score": 9, "section": "Tech"},
        ]
    )
    client = FakeClient(response_text=payload)
    articles = [ClassificationInput(id="a1", title="t", summary="s")]

    results = classify_articles(client, "tech", articles)

    assert [r.id for r in results] == ["a1"]


def test_classify_articles_raises_on_malformed_json() -> None:
    client = FakeClient(response_text="not json at all")
    articles = [ClassificationInput(id="a1", title="t", summary="s")]

    with pytest.raises(json.JSONDecodeError):
        classify_articles(client, "tech", articles)
