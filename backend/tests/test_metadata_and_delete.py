from datetime import datetime, timezone

import pytest

from app.db.session import SessionLocal
from app.db.models import Document, Chunk
from app.rag.pipeline import ingest_document
from app.rag.retriever import retrieve_top_k
from app.rag.embeddings import get_embedding_provider


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.close()


def _cleanup(db_session, *documents):
    for document in documents:
        db_session.query(Chunk).filter(Chunk.document_id == document.id).delete()
        db_session.delete(document)
    db_session.commit()


def test_txt_upload_has_no_page_metadata(db_session, tmp_path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("Just some plain text content for testing.")

    document = ingest_document(db_session, str(file_path), "sample.txt")
    assert document.source_type == "txt"
    assert document.page_count is None

    chunks = db_session.query(Chunk).filter(Chunk.document_id == document.id).all()
    assert len(chunks) > 0
    assert all(c.page_number is None for c in chunks)

    _cleanup(db_session, document)


def test_pdf_upload_has_page_metadata(db_session, tmp_path):
    import fitz

    file_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text((72, 72), "Page one content about apples.")
    page2 = doc.new_page()
    page2.insert_text((72, 72), "Page two content about oranges.")
    doc.save(str(file_path))
    doc.close()

    document = ingest_document(db_session, str(file_path), "sample.pdf")
    assert document.source_type == "pdf"
    assert document.page_count == 2

    chunks = (
        db_session.query(Chunk)
        .filter(Chunk.document_id == document.id)
        .order_by(Chunk.chunk_index)
        .all()
    )
    assert len(chunks) == 2
    assert chunks[0].page_number == 1
    assert chunks[1].page_number == 2

    _cleanup(db_session, document)


def test_delete_document_removes_chunks_and_hides_from_listing(db_session, tmp_path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("Content to be deleted later.")

    document = ingest_document(db_session, str(file_path), "sample.txt")
    document_id = document.id

    chunk_count_before = db_session.query(Chunk).filter(Chunk.document_id == document_id).count()
    assert chunk_count_before > 0

    document.deleted_at = datetime.now(timezone.utc)
    db_session.query(Chunk).filter(Chunk.document_id == document_id).delete()
    db_session.commit()

    chunk_count_after = db_session.query(Chunk).filter(Chunk.document_id == document_id).count()
    assert chunk_count_after == 0

    active_ids = [
        d.id for d in db_session.query(Document).filter(Document.deleted_at.is_(None)).all()
    ]
    assert document_id not in active_ids

    db_session.delete(document)
    db_session.commit()


def test_retrieve_top_k_respects_document_ids_filter(db_session, tmp_path):
    file_a = tmp_path / "doc_a.txt"
    file_a.write_text("This document is about cats and their behavior.")
    file_b = tmp_path / "doc_b.txt"
    file_b.write_text("This document is about dogs and their training.")

    doc_a = ingest_document(db_session, str(file_a), "doc_a.txt")
    doc_b = ingest_document(db_session, str(file_b), "doc_b.txt")

    embedder = get_embedding_provider()
    query_vector = embedder.embed("Tell me about animals")

    results = retrieve_top_k(db_session, query_vector, k=5, document_ids=[doc_a.id])

    assert len(results) > 0
    assert all(chunk.document_id == doc_a.id for chunk, _ in results)

    _cleanup(db_session, doc_a, doc_b)