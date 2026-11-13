"""Optional reranking of search candidates (FR-15, P10-4 and P10-5), behind one interface that tests mock.

The reranker scores (query, chunk) pairs; its raw score is kept, and a logistic map gives the 0-1 relevance that its
own FR-18 thresholds judge (cross-encoder-sigmoid-v1). Any failure while reranking keeps the unreranked order with
degraded=true; only a missing configuration is the caller's error.
"""

import math
from typing import Protocol

from techdocqa.errors import TechDocQAError
from techdocqa.schemas import SearchResult

RERANK_POLICY = "cross-encoder-sigmoid-v1"


class Reranker(Protocol):
    def score(self, query: str, texts: list[str]) -> list[float]:
        """One raw score per text, in input order; higher is more relevant."""


def require_configured(settings) -> None:
    if not settings.retrieval.reranker.model:
        raise TechDocQAError("RERANKER_NOT_CONFIGURED", "No reranker is configured; search without reranking.", stage="configuration")


def build_reranker(settings) -> Reranker:
    """The configured local cross-encoder; RERANKER_UNAVAILABLE when its pinned files are absent or altered."""
    require_configured(settings)
    from techdocqa.retrieval import cross_encoder
    return cross_encoder.from_settings(settings)


def scoring_values(settings, base_mode: str) -> dict:
    """What fixes a reranker relevance, and the candidates it was calibrated on: the base mode's, at most the maximum."""
    require_configured(settings)
    retrieval = settings.retrieval
    from techdocqa.retrieval.cross_encoder import TRUNCATION
    return {"mode": "reranked", "policy": RERANK_POLICY, "base_mode": base_mode, "max_candidates": retrieval.rerank_max_candidates,
            "reranker": retrieval.reranker.model_dump(), "truncation": TRUNCATION}


def sigmoid(value: float) -> float:
    """1 / (1 + e^-x), computed without overflow for large negative scores."""
    if value >= 0:
        return 1 / (1 + math.exp(-value))
    exponent = math.exp(value)
    return exponent / (1 + exponent)


def rerank(query: str, candidates: list[SearchResult], top_k: int, settings) -> tuple[list[SearchResult], str | None]:
    """(results, failure code). At most rerank_max_candidates are sent, in their input order; the rest are dropped.

    Results are ordered by descending reranker score, ties keeping their input order, and keep their earlier ranks,
    scores and relevances alongside the reranker's. On any failure the input order, truncated to top_k, comes back.
    """
    sent = candidates[:settings.retrieval.rerank_max_candidates]
    if not sent:
        return [], None
    try:
        raw = [float(value) for value in build_reranker(settings).score(query, [result.text for result in sent])]
        if len(raw) != len(sent) or not all(math.isfinite(value) for value in raw):
            raise ValueError("the reranker returned an invalid score list")
    except TechDocQAError as error:
        if error.response.error.stage in ("arguments", "configuration"):
            raise
        return candidates[:top_k], error.response.error.code
    except Exception:
        # Model runtimes raise many unrelated exception types; none of their detail reaches the response.
        return candidates[:top_k], "RERANKER_FAILED"
    order = sorted(range(len(sent)), key=lambda index: (-raw[index], index))[:top_k]
    results = []
    for rank, index in enumerate(order, 1):
        result = sent[index]
        earlier = result.relevances or ({mode: result.relevance for mode in result.ranks} if result.relevance is not None else {})
        results.append(result.model_copy(update={
            "rank": rank, "scores": {**result.scores, "rerank": raw[index]}, "ranks": {**result.ranks, "rerank": rank},
            "relevance": sigmoid(raw[index]), "relevances": {**earlier, "rerank": sigmoid(raw[index])}}))
    return results, None
