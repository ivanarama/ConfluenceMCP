"""Score-based merging for multi-variant search results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScoredResult:
    """Page result with relevance score across search variants."""

    item: dict[str, Any]
    score: float
    matched_variants: int = 0


def score_results(
    variant_hits: list[list[dict[str, Any]]],
    *,
    weights: list[float] | None = None,
    limit: int = 10,
) -> list[ScoredResult]:
    """Merge results from multiple variant searches, ranked by cross-variant score.

    Each page accumulates score from every variant that found it.
    Pages appearing in more variants rank higher.

    Args:
        variant_hits: Result lists from client.search(), one per variant query.
        weights: Per-variant weight. Full phrase = 3.0, multi-word = 2.0, single = 1.0.
        limit: Maximum results to return.

    Returns:
        ScoredResult list sorted by score descending.
    """
    if weights is None:
        weights = [1.0] * len(variant_hits)

    scores: dict[str, ScoredResult] = {}

    for idx, hits in enumerate(variant_hits):
        w = weights[idx] if idx < len(weights) else 1.0
        for item in hits:
            if not isinstance(item, dict):
                continue
            iid = str(item.get("id", ""))
            if not iid:
                continue
            if iid in scores:
                scores[iid].score += w
                scores[iid].matched_variants += 1
            else:
                scores[iid] = ScoredResult(item=item, score=w, matched_variants=1)

    ranked = sorted(scores.values(), key=lambda s: (-s.score, -s.matched_variants))
    return ranked[:limit]


def variant_weight(variant: str, original_query: str) -> float:
    """Assign weight based on variant type: full phrase > multi-word > single word."""
    if variant == original_query:
        return 3.0
    word_count = len(variant.split())
    if word_count >= 3:
        return 2.5
    if word_count == 2:
        return 2.0
    return 1.0
