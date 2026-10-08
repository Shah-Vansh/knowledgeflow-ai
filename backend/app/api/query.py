from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.rag.pipeline import answer_question
from app.rag.embeddings import get_embedding_provider
from app.rag.retriever import retrieve_top_k, retrieve_bm25, retrieve_hybrid

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
    Debug endpoint supporting three modes so dense, sparse, and hybrid
    retrieval can be directly compared on the same query. Never hides
    results — only annotates them.
    """
    k = max(1, min(request.k, 20))
    threshold = (
        request.similarity_threshold
        if request.similarity_threshold is not None
        else settings.SIMILARITY_THRESHOLD
    )

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
                "found_by": ["sparse"],
                "above_threshold": True,  # already filtered to real matches by @@ operator
            }
            for chunk, score in results
        ]

    else:  # hybrid
        embedder = get_embedding_provider()
        query_vector = embedder.embed(request.question)
        hybrid = retrieve_hybrid(db, request.question, query_vector, k=k, document_ids=request.document_ids)

        dense_ids = {chunk.id: distance for chunk, distance in hybrid["dense_results"]}
        sparse_ids = {chunk.id: score for chunk, score in hybrid["sparse_results"]}

        formatted = []
        for chunk, rrf_score in hybrid["fused"]:
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
                "rrf_score": float(rrf_score),
                "found_by": found_by,
                "above_threshold": True,  # already the fused top-k
            })

    return {
        "results": formatted,
        "threshold_used": threshold,
        "k_used": k,
        "mode": request.mode,
    }