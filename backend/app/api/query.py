from dataclasses import asdict
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_workspace
from app.core.config import settings
from app.rag.embeddings import get_embedding_provider
from app.rag.pipeline import answer_question, describe_provenance, retrieve_context
from app.rag.query_transform import normalize_transforms
from app.rag.retriever import retrieve_bm25, retrieve_top_k

router = APIRouter(tags=["query"])


class QueryRequest(BaseModel):
    question: str
    document_ids: Optional[List[int]] = None
    transforms: Optional[List[str]] = None  # None = server default (QUERY_TRANSFORMS)
    workspace_id: Optional[int] = None      # None = search every workspace


class RetrieveDebugRequest(BaseModel):
    question: str
    k: int = 5
    similarity_threshold: Optional[float] = None
    document_ids: Optional[List[int]] = None
    mode: str = "hybrid"  # "dense" | "sparse" | "hybrid"
    rerank: bool = False  # hybrid mode only
    transforms: Optional[List[str]] = None  # hybrid mode only; None = no transformation
    workspace_id: Optional[int] = None      # None = search every workspace


def _validated_transforms(names: Optional[List[str]]) -> Optional[List[str]]:
    if names is None:
        return None
    try:
        return normalize_transforms(names)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/query")
def query(request: QueryRequest, db: Session = Depends(get_db)):
    transforms = _validated_transforms(request.transforms)
    if request.workspace_id is not None:
        require_workspace(db, request.workspace_id)
    return answer_question(
        db,
        request.question,
        document_ids=request.document_ids,
        transforms=transforms,
        workspace_id=request.workspace_id,
    )


@router.post("/query/retrieve")
def retrieve_debug(request: RetrieveDebugRequest, db: Session = Depends(get_db)):
    """
    Debug endpoint: dense, sparse, or hybrid retrieval (optionally query-transformed
    and reranked), with no final-answer LLM call. Never hides results — only
    annotates them.
    """
    transforms = _validated_transforms(request.transforms) or []
    if request.workspace_id is not None:
        require_workspace(db, request.workspace_id)

    k = max(1, min(request.k, 20))
    threshold = (
        request.similarity_threshold
        if request.similarity_threshold is not None
        else settings.SIMILARITY_THRESHOLD
    )

    reranked = False
    transformation_payload = None

    if request.mode == "dense":
        embedder = get_embedding_provider()
        query_vector = embedder.embed(request.question)
        results = retrieve_top_k(
            db, query_vector, k=k, document_ids=request.document_ids,
            workspace_id=request.workspace_id,
        )

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
                "found_by_queries": [],
                "above_threshold": float(distance) <= threshold,
            }
            for chunk, distance in results
        ]

    elif request.mode == "sparse":
        results = retrieve_bm25(
            db, request.question, k=k, document_ids=request.document_ids,
            workspace_id=request.workspace_id,
        )

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
                "found_by_queries": [],
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
            transforms=transforms,
            embedder=embedder,
            workspace_id=request.workspace_id,
        )
        hybrid = retrieval["hybrid"]
        reranked = retrieval["reranked"]
        provenance = retrieval["provenance"]

        if retrieval["transformation"] is not None:
            transformation_payload = {
                **asdict(retrieval["transformation"]),
                "jobs": [
                    {
                        "label": job.label,
                        "kind": job.kind,
                        "dense": job.dense,
                        "sparse": job.sparse,
                        "text": job.text,
                    }
                    for job in retrieval["jobs"]
                ],
            }

        # dense_distance / sparse_score describe the ORIGINAL query only
        dense_ids = {chunk.id: distance for chunk, distance in hybrid["dense_results"]}
        sparse_ids = {chunk.id: score for chunk, score in hybrid["sparse_results"]}

        formatted = []
        for item in retrieval["ranked"]:
            chunk = item["chunk"]

            if provenance is not None:
                entry = provenance.get(chunk.id, {})
                methods = {m for ms in entry.values() for m in ms}
                found_by = [m for m in ("dense", "sparse") if m in methods]
                found_by_queries = describe_provenance(entry)
            else:
                found_by = []
                if chunk.id in dense_ids:
                    found_by.append("dense")
                if chunk.id in sparse_ids:
                    found_by.append("sparse")
                found_by_queries = []

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
                "found_by_queries": found_by_queries,
                "above_threshold": True,  # already the final top-k
            })

    return {
        "results": formatted,
        "threshold_used": threshold,
        "k_used": k,
        "mode": request.mode,
        "reranked": reranked,
        "transformation": transformation_payload,
    }