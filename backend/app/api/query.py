from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.rag.pipeline import answer_question
from app.rag.embeddings import get_embedding_provider
from app.rag.retriever import retrieve_top_k

router = APIRouter(tags=["query"])


class QueryRequest(BaseModel):
    question: str
    document_ids: Optional[List[int]] = None


class RetrieveDebugRequest(BaseModel):
    question: str
    k: int = 5
    similarity_threshold: Optional[float] = None
    document_ids: Optional[List[int]] = None


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
    Debug endpoint: returns the raw ranked candidate list from retrieval,
    with no LLM call involved. Never hides results — only flags which ones
    would pass the given (or default) similarity threshold, so the person
    using this can see the full picture rather than a pre-filtered one.
    """
    k = max(1, min(request.k, 20))
    threshold = (
        request.similarity_threshold
        if request.similarity_threshold is not None
        else settings.SIMILARITY_THRESHOLD
    )

    embedder = get_embedding_provider()
    query_vector = embedder.embed(request.question)

    results = retrieve_top_k(db, query_vector, k=k, document_ids=request.document_ids)

    formatted = [
        {
            "chunk_id": chunk.id,
            "content": chunk.content,
            "distance": float(distance),
            "above_threshold": float(distance) <= threshold,
            "document_id": chunk.document_id,
            "filename": chunk.document.filename,
            "page_number": chunk.page_number,
        }
        for chunk, distance in results
    ]

    return {
        "results": formatted,
        "threshold_used": threshold,
        "k_used": k,
    }