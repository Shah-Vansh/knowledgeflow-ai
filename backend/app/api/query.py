from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.rag.pipeline import answer_question, retrieve_context
from app.rag.embeddings import get_embedding_provider
from app.rag.retriever import retrieve_top_k, retrieve_bm25

router = APIRouter(tags=["query"])


class QueryRequest(BaseModel):
    question: str
    document_ids: Optional[List[int]] = None


class RetrieveDebugRequest(BaseModel):
    question: str
    k: int = 5
    similarity_threshold: Optional[float] = None
    document_ids: Optional[List[int]] = None
    mode: str = "hybrid"  # "dense" | "sparse" | "hybrid"
    rerank: bool = False  # only applies to hybrid mode


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/query")
def query(request: QueryRequest, db: Session = Depends(get_db)):
    return answer_question(db, request.question, document_ids=request.document_ids)


@router.post("/query/retrieve")
def retrieve_debug(request: RetrieveDebugRequest, db: Session = Depends(get_db)):
    """
    Debug endpoint: dense, sparse, or hybrid (optionally reranked) retrieval,
    with no LLM call. Never hides results — only annotates them.
    """
    k = max(1, min(request.k, 20))
    threshold = (
        request.similarity_threshold
        if request.similarity_threshold is not None
        else settings.SIMILARITY_THRESHOLD
    )

    reranked = False

    if request.mode == "dense":
        embedder = get_embedding_provider()
        query_vector = embedder.embed(request.question)
        results = retrieve_top_k(db, query_vector, k=k, document_ids=request.document_ids)

        formatted = [
            {
                "chunk_id": chunk.id,
                "content": chunk.content,
                "document_id": chunk.document_id,
                "filename": chunk.document.filename,
                "page_number": chunk.page_number,
                "dense_distance": float(distance),
                "sparse_score": None,
                "rrf_score": None,
                "rerank_score": None,
                "pre_rerank_rank": None,
                "post_rerank_rank": None,
                "found_by": ["dense"],
                "above_threshold": float(distance) <= threshold,
            }
            for chunk, distance in results
        ]

    elif request.mode == "sparse":
        results = retrieve_bm25(db, request.question, k=k, document_ids=request.document_ids)

        formatted = [
            {
                "chunk_id": chunk.id,
                "content": chunk.content,
                "document_id": chunk.document_id,
                "filename": chunk.document.filename,
                "page_number": chunk.page_number,
                "dense_distance": None,
                "sparse_score": float(score),
                "rrf_score": None,
                "rerank_score": None,
                "pre_rerank_rank": None,
                "post_rerank_rank": None,
                "found_by": ["sparse"],
                "above_threshold": True,  # already filtered to real matches by @@ operator
            }
            for chunk, score in results
        ]

    else:  # hybrid
        embedder = get_embedding_provider()
        query_vector = embedder.embed(request.question)

        retrieval = retrieve_context(
            db,
            request.question,
            query_vector,
            k=k,
            document_ids=request.document_ids,
            use_rerank=request.rerank,
        )
        hybrid = retrieval["hybrid"]
        reranked = retrieval["reranked"]

        dense_ids = {chunk.id: distance for chunk, distance in hybrid["dense_results"]}
        sparse_ids = {chunk.id: score for chunk, score in hybrid["sparse_results"]}

        formatted = []
        for item in retrieval["ranked"]:
            chunk = item["chunk"]
            found_by = []
            if chunk.id in dense_ids:
                found_by.append("dense")
            if chunk.id in sparse_ids:
                found_by.append("sparse")

            formatted.append({
                "chunk_id": chunk.id,
                "content": chunk.content,
                "document_id": chunk.document_id,
                "filename": chunk.document.filename,
                "page_number": chunk.page_number,
                "dense_distance": float(dense_ids[chunk.id]) if chunk.id in dense_ids else None,
                "sparse_score": float(sparse_ids[chunk.id]) if chunk.id in sparse_ids else None,
                "rrf_score": float(item["fused_score"]),
                "rerank_score": float(item["score"]) if reranked else None,
                "pre_rerank_rank": item["pre_rank"] if reranked else None,
                "post_rerank_rank": item["post_rank"] if reranked else None,
                "found_by": found_by,
                "above_threshold": True,  # already the final top-k
            })

    return {
        "results": formatted,
        "threshold_used": threshold,
        "k_used": k,
        "mode": request.mode,
        "reranked": reranked,
    }