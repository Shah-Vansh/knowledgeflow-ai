from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple

from sentence_transformers import CrossEncoder

from app.core.config import settings


class Reranker(ABC):
    """
    Abstract interface for second-stage reranking. A reranker scores how well
    each passage answers the query. Only the ORDER of scores matters — they are
    raw model outputs and are not comparable to cosine distances or RRF scores.
    """

    @abstractmethod
    def score(self, query: str, passages: List[str]) -> List[float]:
        ...


class CrossEncoderReranker(Reranker):
    """
    Local cross-encoder (sentence-transformers). Unlike the embedding model, which
    encodes query and chunk separately, a cross-encoder reads them together as one
    input, so it can judge their interaction — more accurate, but nothing can be
    precomputed, which is why it only runs over a small candidate pool.
    The model downloads once (~90 MB) on first use, then loads from cache.
    """

    _model = None  # loaded lazily, shared across instances

    def __init__(self):
        if CrossEncoderReranker._model is None:
            CrossEncoderReranker._model = CrossEncoder(settings.RERANK_MODEL)
        self._model = CrossEncoderReranker._model

    def score(self, query: str, passages: List[str]) -> List[float]:
        if not passages:
            return []
        pairs = [(query, passage) for passage in passages]
        scores = self._model.predict(pairs)
        return [float(s) for s in scores]


def get_reranker() -> Reranker:
    return CrossEncoderReranker()


def rerank_candidates(
    reranker: Reranker,
    query: str,
    candidates: List[Tuple[Any, float]],
    top_k: int,
) -> List[Dict[str, Any]]:
    """
    candidates: [(chunk, fused_score), ...] in their pre-rerank order.
    Returns the best `top_k` as dicts: chunk, score (rerank score), fused_score,
    pre_rank (position in the input list), post_rank (position after reranking).
    """
    if not candidates:
        return []

    scores = reranker.score(query, [chunk.content for chunk, _ in candidates])

    scored = [
        {
            "chunk": chunk,
            "score": float(score),
            "fused_score": float(fused_score),
            "pre_rank": pre_rank,
        }
        for pre_rank, ((chunk, fused_score), score) in enumerate(zip(candidates, scores), start=1)
    ]

    scored.sort(key=lambda item: item["score"], reverse=True)

    top = scored[:top_k]
    for post_rank, item in enumerate(top, start=1):
        item["post_rank"] = post_rank

    return top