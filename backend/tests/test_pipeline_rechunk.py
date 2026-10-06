import pytest

from app.db.session import SessionLocal
from app.db.models import Document, Chunk
from app.rag.pipeline import ingest_document, rechunk_document


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.close()


def test_rechunk_replaces_existing_chunks(db_session, tmp_path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text(
        "Paragraph one has some content here.\n\n"
        "Paragraph two has different content here.\n\n"
        "Paragraph three wraps things up."
    )

    document = ingest_document(db_session, str(file_path), "sample.txt")
    assert document.status == "processed"

    original_count = (
        db_session.query(Chunk).filter(Chunk.document_id == document.id).count()
    )
    assert original_count > 0

    result = rechunk_document(db_session, document.id, strategy="recursive", chunk_size=1000, overlap=0)

    new_count = (
        db_session.query(Chunk).filter(Chunk.document_id == document.id).count()
    )
    assert new_count == result["chunk_count"]
    # recursive with a large chunk_size should merge all 3 short paragraphs into 1 chunk
    assert new_count == 1

    db_session.query(Chunk).filter(Chunk.document_id == document.id).delete()
    db_session.delete(document)
    db_session.commit()