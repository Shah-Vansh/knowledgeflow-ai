from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document


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


def retrieve_bm25(
    db: Session,
    query_text: str,
    k: int = 20,
    document_ids: Optional[List[int]] = None,
) -> List[Tuple[Chunk, float]]:
    """
    Sparse (keyword) retrieval using PostgreSQL full-text search.
    Higher ts_rank score = more relevant. Only returns chunks that actually
    contain at least one query term (unlike dense search, which always
    returns k results regardless of relevance) — this is a key behavioral
    difference worth noticing: sparse search can legitimately return nothing.
    """
    tsquery = func.plainto_tsquery("english", query_text)
    rank = func.ts_rank(Chunk.search_vector, tsquery)

    query = (
        db.query(Chunk, rank.label("score"))
        .join(Document, Chunk.document_id == Document.id)
        .filter(Document.deleted_at.is_(None))
        .filter(Chunk.search_vector.op("@@")(tsquery))
    )

    if document_ids:
        query = query.filter(Chunk.document_id.in_(document_ids))

    results = query.order_by(rank.desc()).limit(k).all()
    return results


def reciprocal_rank_fusion(
    dense_results: List[Tuple[Chunk, float]],
    sparse_results: List[Tuple[Chunk, float]],
    rrf_k: int = 60,
    top_k: int = 5,
) -> List[Tuple[Chunk, float]]:
    """
    Fuses two ranked lists by rank POSITION, not raw score — dense distances
    and BM25 scores live on completely different, incomparable scales, so
    averaging them directly would be meaningless. RRF sidesteps that by only
    asking "how high did this chunk rank in each list?"

    rrf_k=60 is the standard constant from the original RRF paper — it
    dampens the influence of very top ranks slightly so the fusion isn't
    dominated by a single system's #1 pick.
    """
    scores: Dict[int, float] = {}
    chunks_by_id: Dict[int, Chunk] = {}

    for rank, (chunk, _) in enumerate(dense_results, start=1):
        scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (rrf_k + rank)
        chunks_by_id[chunk.id] = chunk

    for rank, (chunk, _) in enumerate(sparse_results, start=1):
        scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (rrf_k + rank)
        chunks_by_id[chunk.id] = chunk

    fused = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [(chunks_by_id[chunk_id], score) for chunk_id, score in fused[:top_k]]


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

    Returns a dict (not just a list) because downstream grounding logic
    needs more than the fused ranking alone:
      - fused: the final [(chunk, rrf_score), ...] list, length <= k
      - best_dense_distance: the single best cosine distance found across
        the dense candidate pool (None if dense found nothing, which
        shouldn't normally happen but is handled defensively)
      - sparse_hit_count: how many chunks sparse search matched at all
        (0 means the query shares no real keywords with anything ingested)

    These two signals together let the pipeline distinguish "nothing
    relevant exists" from "relevant by one method but not the other" —
    the second case is exactly what hybrid search is supposed to rescue.
    """
    dense_results = retrieve_top_k(db, query_embedding, k=candidate_pool, document_ids=document_ids)
    sparse_results = retrieve_bm25(db, query_text, k=candidate_pool, document_ids=document_ids)

    fused = reciprocal_rank_fusion(dense_results, sparse_results, rrf_k=60, top_k=k)

    best_dense_distance = min((distance for _, distance in dense_results), default=None)

    return {
        "fused": fused,
        "dense_results": dense_results,
        "sparse_results": sparse_results,
        "best_dense_distance": best_dense_distance,
        "sparse_hit_count": len(sparse_results),
    }