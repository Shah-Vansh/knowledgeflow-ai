import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Document, Chunk
from app.rag.parsers import extract_text
from app.rag.chunker import chunk_text
from app.rag.embeddings import get_embedding_provider
from app.rag.llm import get_llm_provider
from app.rag.retriever import retrieve_top_k

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
    document = Document(filename=filename, status="processing")
    db.add(document)
    db.commit()
    db.refresh(document)

    try:
        text = extract_text(file_path, filename)
        document.raw_text = text

        pieces = chunk_text(text, strategy=strategy, chunk_size=chunk_size, overlap=overlap)

        if not pieces:
            document.status = "failed"
            db.commit()
            return document

        embedder = get_embedding_provider()
        vectors = embedder.embed_batch(pieces)

        for index, (piece, vector) in enumerate(zip(pieces, vectors)):
            db.add(
                Chunk(
                    document_id=document.id,
                    content=piece,
                    embedding=vector,
                    chunk_index=index,
                    strategy=strategy,
                    chunk_size=chunk_size,
                    overlap=overlap,
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


def answer_question(db: Session, question: str, k: int = None) -> dict:
    k = k or settings.TOP_K

    embedder = get_embedding_provider()
    query_vector = embedder.embed(question)

    results = retrieve_top_k(db, query_vector, k=k)

    if not results:
        return {"answer": NO_INFO_RESPONSE, "chunks_used": []}

    best_distance = results[0][1]
    if best_distance > settings.SIMILARITY_THRESHOLD:
        return {"answer": NO_INFO_RESPONSE, "chunks_used": []}

    context_blocks = []
    chunks_used = []
    for chunk, distance in results:
        context_blocks.append(chunk.content)
        chunks_used.append(
            {
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "chunk_index": chunk.chunk_index,
                "distance": float(distance),
            }
        )

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

    return {"answer": answer, "chunks_used": chunks_used}