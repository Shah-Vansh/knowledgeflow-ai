import logging
import time
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Document, Chunk
from app.rag.parsers import extract_pages
from app.rag.chunker import chunk_text
from app.rag.embeddings import get_embedding_provider
from app.rag.llm import LLMProvider, get_llm_provider
from app.rag.query_transform import (
    normalize_transforms,
    plan_search_jobs,
    transform_query,
)
from app.rag.reranker import Reranker, get_reranker, rerank_candidates
from app.rag.retriever import (
    RRF_K,
    reciprocal_rank_fusion_many,
    retrieve_bm25,
    retrieve_bm25_any_term,
    retrieve_hybrid,
    retrieve_top_k,
)

logger = logging.getLogger(__name__)

NO_INFO_RESPONSE = (
    "I don't have enough information in the available knowledge base "
    "to answer this reliably."
)


def ingest_document(
    db: Session,
    file_path: str,
    filename: str,
    strategy: str = "fixed_size",
    chunk_size: int = 500,
    overlap: int = 0,
    workspace_id: Optional[int] = None,
) -> Document:
    """
    workspace_id=None leaves the column to its database default (the General
    workspace). Callers that accept a workspace from a user must verify it exists.
    """
    source_type = filename.lower().rsplit(".", 1)[-1] if "." in filename else None

    document = Document(filename=filename, status="processing", source_type=source_type)
    if workspace_id is not None:
        document.workspace_id = workspace_id
    db.add(document)
    db.commit()
    db.refresh(document)

    try:
        pages = extract_pages(file_path, filename)

        if source_type == "pdf":
            document.page_count = len(pages)

        document.raw_text = "\n\n".join(text for _, text in pages)

        all_pieces = []  # list of (piece_text, page_number)
        for page_number, page_text in pages:
            pieces = chunk_text(page_text, strategy=strategy, chunk_size=chunk_size, overlap=overlap)
            for piece in pieces:
                all_pieces.append((piece, page_number))

        if not all_pieces:
            document.status = "failed"
            db.commit()
            return document

        embedder = get_embedding_provider()
        vectors = embedder.embed_batch([piece for piece, _ in all_pieces])

        for index, ((piece, page_number), vector) in enumerate(zip(all_pieces, vectors)):
            # search_vector is NOT set here — it's a PostgreSQL generated column.
            db.add(
                Chunk(
                    document_id=document.id,
                    content=piece,
                    embedding=vector,
                    chunk_index=index,
                    strategy=strategy,
                    chunk_size=chunk_size,
                    overlap=overlap,
                    page_number=page_number,
                )
            )

        document.status = "processed"
        db.commit()

    except Exception as exc:
        logger.error("Ingestion failed for %s: %s", filename, exc)
        document.status = "failed"
        db.commit()

    return document


def rechunk_document(db: Session, document_id: int, strategy: str, chunk_size: int, overlap: int) -> dict:
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise ValueError("Document not found")
    if not document.raw_text:
        raise ValueError("No stored raw text for this document — re-upload to enable rechunking")

    db.query(Chunk).filter(Chunk.document_id == document_id).delete()
    db.commit()

    pieces = chunk_text(document.raw_text, strategy=strategy, chunk_size=chunk_size, overlap=overlap)

    if not pieces:
        return {"document_id": document_id, "chunk_count": 0}

    embedder = get_embedding_provider()
    vectors = embedder.embed_batch(pieces)

    for index, (piece, vector) in enumerate(zip(pieces, vectors)):
        db.add(
            Chunk(
                document_id=document_id,
                content=piece,
                embedding=vector,
                chunk_index=index,
                strategy=strategy,
                chunk_size=chunk_size,
                overlap=overlap,
            )
        )
    db.commit()

    return {"document_id": document_id, "chunk_count": len(pieces)}


def describe_provenance(entry: Dict[str, List[str]]) -> List[str]:
    """{'original': ['dense'], 'expand': ['sparse']} -> ['original: dense', 'expand: sparse']"""
    described = []
    for label, methods in entry.items():
        ordered = [m for m in ("dense", "sparse") if m in methods]
        described.append(f"{label}: {'+'.join(ordered)}")
    return described


def _plain_ranked(candidates, k: int) -> List[dict]:
    """Top-k of a fused list with no reranking (pre_rank == post_rank)."""
    return [
        {
            "chunk": chunk,
            "score": float(score),
            "fused_score": float(score),
            "pre_rank": position,
            "post_rank": position,
        }
        for position, (chunk, score) in enumerate(candidates[:k], start=1)
    ]


def _apply_rerank(question: str, candidates, k: int, reranker: Optional[Reranker]) -> List[dict]:
    """Cross-encoder rerank. Always scores against the ORIGINAL question."""
    active_reranker = reranker or get_reranker()

    started = time.perf_counter()
    ranked = rerank_candidates(active_reranker, question, candidates, top_k=k)
    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info("Reranked %d candidates in %.0f ms", len(candidates), elapsed_ms)

    return ranked


def _retrieve_with_transforms(
    db: Session,
    question: str,
    query_vector: List[float],
    k: int,
    document_ids: Optional[List[int]],
    requested: List[str],
    llm: Optional[LLMProvider],
    embedder,
    use_rerank: bool,
    reranker: Optional[Reranker],
    workspace_id: Optional[int] = None,
) -> dict:
    llm = llm or get_llm_provider()
    embedder = embedder or get_embedding_provider()

    # ONE LLM call returns every enabled transformation. Fails open: on any error
    # the result is flagged and only the original query is searched.
    transformation = transform_query(llm, question, requested)
    jobs = plan_search_jobs(transformation)

    # One batched embedding call for every dense job except the original,
    # whose vector the caller already computed.
    extra_dense = [(i, job) for i, job in enumerate(jobs) if job.dense and job.kind != "original"]
    extra_vectors: Dict[int, List[float]] = {}
    if extra_dense:
        embedded = embedder.embed_batch([job.text for _, job in extra_dense])
        for (i, _), vector in zip(extra_dense, embedded):
            extra_vectors[i] = vector

    depth = max(k, settings.RERANK_CANDIDATES)

    runs = []  # one entry per ranked list: label, method, results
    for i, job in enumerate(jobs):
        if job.dense:
            vector = query_vector if job.kind == "original" else extra_vectors[i]
            runs.append({
                "label": job.label,
                "method": "dense",
                "results": retrieve_top_k(
                    db, vector, k=depth, document_ids=document_ids, workspace_id=workspace_id
                ),
            })
        if job.sparse:
            if job.kind == "expand":
                results = retrieve_bm25_any_term(
                    db, job.terms, k=depth, document_ids=document_ids, workspace_id=workspace_id
                )
            else:
                results = retrieve_bm25(
                    db, job.text, k=depth, document_ids=document_ids, workspace_id=workspace_id
                )
            runs.append({"label": job.label, "method": "sparse", "results": results})

    fused_size = depth if use_rerank else k
    fused = reciprocal_rank_fusion_many(
        [run["results"] for run in runs], rrf_k=RRF_K, top_k=fused_size
    )

    # Provenance: which query/method surfaced each chunk (for the debug UI)
    provenance: Dict[int, Dict[str, List[str]]] = {}
    for run in runs:
        for chunk, _ in run["results"]:
            provenance.setdefault(chunk.id, {}).setdefault(run["label"], []).append(run["method"])

    # Grounding signals come from the ORIGINAL query only. Transformations may
    # widen what is retrieved, never what counts as grounded.
    original_dense = next(r["results"] for r in runs if r["label"] == "original" and r["method"] == "dense")
    original_sparse = next(r["results"] for r in runs if r["label"] == "original" and r["method"] == "sparse")

    hybrid = {
        "fused": fused,
        "dense_results": original_dense,
        "sparse_results": original_sparse,
        "best_dense_distance": min((distance for _, distance in original_dense), default=None),
        "sparse_hit_count": len(original_sparse),
    }

    ranked = _apply_rerank(question, fused, k, reranker) if use_rerank else _plain_ranked(fused, k)

    return {
        "hybrid": hybrid,
        "ranked": ranked,
        "reranked": use_rerank,
        "transformation": transformation,
        "jobs": jobs,
        "provenance": provenance,
    }


def retrieve_context(
    db: Session,
    question: str,
    query_vector: List[float],
    k: int,
    document_ids: Optional[List[int]] = None,
    reranker: Optional[Reranker] = None,
    use_rerank: Optional[bool] = None,
    transforms: Optional[List[str]] = None,
    llm: Optional[LLMProvider] = None,
    embedder=None,
    workspace_id: Optional[int] = None,
) -> dict:
    """
    Retrieval with no final-answer LLM call.

    transforms=None or [] means NO query transformation (exactly Phase 6 behavior);
    the config default is applied one level up, in answer_question.
    workspace_id (when given) restricts every search to that workspace, in SQL.

    Returns:
      hybrid:         signals dict (fused, dense/sparse lists of the ORIGINAL query,
                      best_dense_distance, sparse_hit_count)
      ranked:         final top-k as dicts: chunk, score, fused_score, pre_rank, post_rank
      reranked:       whether the cross-encoder was applied
      transformation: TransformResult, or None when no transforms were requested
      jobs:           the planned SearchJobs, or None
      provenance:     {chunk_id: {query label: [methods]}}, or None
    """
    if use_rerank is None:
        use_rerank = settings.RERANK_ENABLED

    requested = normalize_transforms(transforms)

    if requested:
        return _retrieve_with_transforms(
            db, question, query_vector, k, document_ids, requested,
            llm, embedder, use_rerank, reranker, workspace_id=workspace_id,
        )

    if not use_rerank:
        hybrid = retrieve_hybrid(
            db, question, query_vector, k=k, document_ids=document_ids, workspace_id=workspace_id
        )
        ranked = _plain_ranked(hybrid["fused"], k)
    else:
        pool = max(k, settings.RERANK_CANDIDATES)
        hybrid = retrieve_hybrid(
            db, question, query_vector, k=pool, document_ids=document_ids,
            candidate_pool=pool, workspace_id=workspace_id,
        )
        ranked = _apply_rerank(question, hybrid["fused"], k, reranker)

    return {
        "hybrid": hybrid,
        "ranked": ranked,
        "reranked": use_rerank,
        "transformation": None,
        "jobs": None,
        "provenance": None,
    }


def answer_question(
    db: Session,
    question: str,
    k: int = None,
    document_ids: Optional[List[int]] = None,
    reranker: Optional[Reranker] = None,
    transforms: Optional[List[str]] = None,
    llm: Optional[LLMProvider] = None,
    workspace_id: Optional[int] = None,
) -> dict:
    k = k or settings.TOP_K

    if transforms is None:
        try:
            transforms = normalize_transforms(settings.default_transforms)
        except ValueError as exc:
            logger.warning("Ignoring invalid QUERY_TRANSFORMS setting: %s", exc)
            transforms = []

    embedder = get_embedding_provider()
    query_vector = embedder.embed(question)

    retrieval = retrieve_context(
        db, question, query_vector, k=k, document_ids=document_ids,
        reranker=reranker, transforms=transforms, llm=llm, embedder=embedder,
        workspace_id=workspace_id,
    )
    hybrid = retrieval["hybrid"]
    ranked = retrieval["ranked"]
    transformation = retrieval["transformation"]

    meta = {
        "transforms_used": list(transformation.requested) if transformation else [],
        "transformation_fallback": bool(transformation.fallback_used) if transformation else False,
    }

    if not ranked:
        return {"answer": NO_INFO_RESPONSE, "sources": [], **meta}

    # Grounding gate: proceed only if EITHER dense found something within the
    # similarity threshold OR sparse found a keyword match — judged on the
    # ORIGINAL question's own retrieval signals, never on transformed queries.
    dense_ok = (
        hybrid["best_dense_distance"] is not None
        and hybrid["best_dense_distance"] <= settings.SIMILARITY_THRESHOLD
    )
    sparse_ok = hybrid["sparse_hit_count"] > 0

    if not dense_ok and not sparse_ok:
        return {"answer": NO_INFO_RESPONSE, "sources": [], **meta}

    context_blocks = []
    source_map = {}

    for item in ranked:
        chunk = item["chunk"]
        score = item["score"]
        context_blocks.append(chunk.content)
        key = (chunk.document_id, chunk.page_number)

        if key not in source_map:
            source_map[key] = {
                "document_id": chunk.document_id,
                "filename": chunk.document.filename,
                "page_number": chunk.page_number,
                "chunk_ids": [],
                "score": score,
            }

        source_map[key]["chunk_ids"].append(chunk.id)
        source_map[key]["score"] = max(source_map[key]["score"], score)

    sources = sorted(source_map.values(), key=lambda s: s["score"], reverse=True)

    context = "\n\n---\n\n".join(context_blocks)

    prompt = f"""You are a helpful assistant answering questions using ONLY the context below.
If the context does not contain enough information to answer the question, respond exactly with:
"{NO_INFO_RESPONSE}"
Do not use any outside knowledge. Do not invent facts, sources, or details not present in the context.

Context:
{context}

Question: {question}

Answer:"""

    answer = (llm or get_llm_provider()).generate(prompt)

    return {"answer": answer, "sources": sources, **meta}