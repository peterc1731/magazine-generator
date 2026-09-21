from __future__ import annotations

import math
from typing import Protocol


class EmbeddingProvider(Protocol):
    """A real provider (e.g. Voyage AI, Anthropic's recommended embeddings
    partner) plugs in here. Not wired up yet — Anthropic has no first-party
    embeddings endpoint, and this codebase hasn't verified Voyage's current
    SDK/model name against live docs, so implementing it now would mean
    guessing an external API shape. The clustering algorithm below is
    provider-agnostic and works against embeddings from whatever the caller
    supplies.
    """

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def cluster_duplicates(
    items: list[tuple[str, list[float]]],
    similarity_threshold: float = 0.92,
) -> list[list[str]]:
    """Groups item ids whose embedding vectors are near-duplicates (e.g. the
    same story covered by BBC and the Guardian).

    Simple greedy single-link clustering against each cluster's first member:
    good enough for a weekly batch of articles from a handful of sources, not
    meant to scale beyond that.
    """
    clusters: list[list[str]] = []
    cluster_reps: list[list[float]] = []

    for item_id, vector in items:
        placed = False
        for cluster, rep in zip(clusters, cluster_reps, strict=True):
            if cosine_similarity(vector, rep) >= similarity_threshold:
                cluster.append(item_id)
                placed = True
                break
        if not placed:
            clusters.append([item_id])
            cluster_reps.append(vector)

    return clusters


def pick_representatives(clusters: list[list[str]]) -> list[str]:
    """The first item in each cluster stands in for the group — callers can
    control which one that is by ordering `items` (e.g. preferred sources
    first) before calling `cluster_duplicates`."""
    return [cluster[0] for cluster in clusters]
