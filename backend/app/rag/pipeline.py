import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Document, Chunk
from app.rag.parsers import extract_pages
from app.rag.chunker import chunk_text
from app.rag.embeddings import get_embedding_provider
from app.rag.llm import get_llm_provider
from app.rag.retriever import retrieve_hybrid

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
) -> Document:
    source_type = filename.lower().rsplit(".", 1)[-1] if "." in filename else None

    document = Document(filename=filename, status="processing", source_type=source_type)
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
            # search_vector is NOT set here — it's a PostgreSQL GENERATED
            # ALWAYS AS column, computed automatically from `content`.
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


def answer_question(db: Session, question: str, k: int = None, document_ids: Optional[List[int]] = None) -> dict:
    k = k or settings.TOP_K

    embedder = get_embedding_provider()
    query_vector = embedder.embed(question)

    hybrid = retrieve_hybrid(db, question, query_vector, k=k, document_ids=document_ids)
    fused_results = hybrid["fused"]

    if not fused_results:
        return {"answer": NO_INFO_RESPONSE, "sources": []}

    # Grounding gate: proceed only if EITHER dense found something within
    # the similarity threshold OR sparse found an actual keyword match.
    # This preserves Phase 1's no-hallucination guarantee while allowing
    # hybrid's two different "this is relevant" signals to each count.
    dense_ok = (
        hybrid["best_dense_distance"] is not None
        and hybrid["best_dense_distance"] <= settings.SIMILARITY_THRESHOLD
    )
    sparse_ok = hybrid["sparse_hit_count"] > 0

    if not dense_ok and not sparse_ok:
        return {"answer": NO_INFO_RESPONSE, "sources": []}

    context_blocks = []
    source_map = {}

    for chunk, rrf_score in fused_results:
        context_blocks.append(chunk.content)
        key = (chunk.document_id, chunk.page_number)

        if key not in source_map:
            source_map[key] = {
                "document_id": chunk.document_id,
                "filename": chunk.document.filename,
                "page_number": chunk.page_number,
                "chunk_ids": [],
                "score": rrf_score,
            }

        source_map[key]["chunk_ids"].append(chunk.id)
        source_map[key]["score"] = max(source_map[key]["score"], rrf_score)

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

    llm = get_llm_provider()
    answer = llm.generate(prompt)

    return {"answer": answer, "sources": sources}