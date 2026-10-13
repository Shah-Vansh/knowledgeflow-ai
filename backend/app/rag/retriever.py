import re
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document

RRF_K = 60  # standard constant from the original Reciprocal Rank Fusion paper


def retrieve_top_k(
    db: Session,
    query_embedding: List[float],
    k: int = 5,
    document_ids: Optional[List[int]] = None,
) -> List[Tuple[Chunk, float]]:
    """
    Dense retrieval. Cosine-distance similarity search via pgvector.
    Lower distance = more similar. Always excludes soft-deleted documents.
    """
    query = (
        db.query(Chunk, Chunk.embedding.cosine_distance(query_embedding).label("distance"))
        .join(Document, Chunk.document_id == Document.id)
        .filter(Document.deleted_at.is_(None))
    )

    if document_ids:
        query = query.filter(Chunk.document_id.in_(document_ids))

    results = (
        query.order_by(Chunk.embedding.cosine_distance(query_embedding))
        .limit(k)
        .all()
    )
    return results


def _run_fts(
    db: Session,
    tsquery,
    k: int,
    document_ids: Optional[List[int]],
) -> List[Tuple[Chunk, float]]:
    rank = func.ts_rank(Chunk.search_vector, tsquery)

    query = (
        db.query(Chunk, rank.label("score"))
        .join(Document, Chunk.document_id == Document.id)
        .filter(Document.deleted_at.is_(None))
        .filter(Chunk.search_vector.op("@@")(tsquery))
    )

    if document_ids:
        query = query.filter(Chunk.document_id.in_(document_ids))

    return query.order_by(rank.desc()).limit(k).all()


def retrieve_bm25(
    db: Session,
    query_text: str,
    k: int = 20,
    document_ids: Optional[List[int]] = None,
) -> List[Tuple[Chunk, float]]:
    """
    Sparse (keyword) retrieval using PostgreSQL full-text search (ts_rank —
    note: NOT true BM25). Every query term must appear in a chunk (AND), so this
    can legitimately return nothing.
    """
    tsquery = func.plainto_tsquery("english", query_text)
    return _run_fts(db, tsquery, k, document_ids)


def retrieve_bm25_any_term(
    db: Session,
    terms: List[str],
    k: int = 20,
    document_ids: Optional[List[int]] = None,
) -> List[Tuple[Chunk, float]]:
    """
    Sparse retrieval with OR semantics across `terms`. A multi-word term is
    treated as a group that must match together (AND within the term), so
    ["machine learning", "neural"] means (machine & learning) | neural.

    The tsquery text is built ONLY from \\w+ word tokens, so nothing a language
    model returns can inject full-text-search operators.
    """
    groups = []
    for term in terms:
        tokens = re.findall(r"\w+", (term or "").lower())
        if tokens:
            groups.append("(" + " & ".join(tokens) + ")")

    if not groups:
        return []

    tsquery = func.to_tsquery("english", " | ".join(groups))
    return _run_fts(db, tsquery, k, document_ids)


def reciprocal_rank_fusion_many(
    ranked_lists: List[List[Tuple[Chunk, float]]],
    rrf_k: int = RRF_K,
    top_k: int = 5,
) -> List[Tuple[Chunk, float]]:
    """
    Fuses any number of ranked lists by rank POSITION, not raw score — distances,
    full-text scores and rerank scores live on incomparable scales. A chunk found
    by several lists accumulates score from each, so agreement is rewarded.
    """
    scores: Dict[int, float] = {}
    chunks_by_id: Dict[int, Chunk] = {}

    for ranked in ranked_lists:
        for rank, (chunk, _) in enumerate(ranked, start=1):
            scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (rrf_k + rank)
            chunks_by_id[chunk.id] = chunk

    fused = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [(chunks_by_id[chunk_id], score) for chunk_id, score in fused[:top_k]]


def reciprocal_rank_fusion(
    dense_results: List[Tuple[Chunk, float]],
    sparse_results: List[Tuple[Chunk, float]],
    rrf_k: int = RRF_K,
    top_k: int = 5,
) -> List[Tuple[Chunk, float]]:
    """Two-list convenience wrapper (Phase 5 API) around the N-list version."""
    return reciprocal_rank_fusion_many([dense_results, sparse_results], rrf_k=rrf_k, top_k=top_k)


def retrieve_hybrid(
    db: Session,
    query_text: str,
    query_embedding: List[float],
    k: int = 5,
    document_ids: Optional[List[int]] = None,
    candidate_pool: int = 20,
) -> dict:
    """
    Runs dense and sparse retrieval independently, fuses them with RRF.

    Returns a dict because downstream grounding logic needs more than the ranking:
      - fused: final [(chunk, rrf_score), ...], length <= k
      - dense_results / sparse_results: the two candidate lists
      - best_dense_distance: best cosine distance in the dense pool (None if empty)
      - sparse_hit_count: how many chunks sparse search matched at all
    """
    dense_results = retrieve_top_k(db, query_embedding, k=candidate_pool, document_ids=document_ids)
    sparse_results = retrieve_bm25(db, query_text, k=candidate_pool, document_ids=document_ids)

    fused = reciprocal_rank_fusion(dense_results, sparse_results, rrf_k=RRF_K, top_k=k)

    best_dense_distance = min((distance for _, distance in dense_results), default=None)

    return {
        "fused": fused,
        "dense_results": dense_results,
        "sparse_results": sparse_results,
        "best_dense_distance": best_dense_distance,
        "sparse_hit_count": len(sparse_results),
    }