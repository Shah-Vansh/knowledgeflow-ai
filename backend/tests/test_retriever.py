import pytest

from app.db.session import SessionLocal
from app.db.models import Document, Chunk
from app.rag.retriever import retrieve_top_k
from app.core.config import settings


def _vector(active_index: int) -> list[float]:
    v = [0.0] * settings.EMBEDDING_DIM
    v[active_index] = 1.0
    return v


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.close()


def test_retrieve_top_k_orders_by_similarity(db_session):
    document = Document(filename="test.txt", status="processed")
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)

    close_chunk = Chunk(document_id=document.id, content="close", embedding=_vector(0), chunk_index=0)
    far_chunk = Chunk(document_id=document.id, content="far", embedding=_vector(1), chunk_index=1)
    db_session.add_all([close_chunk, far_chunk])
    db_session.commit()

    query_vector = _vector(0)
    results = retrieve_top_k(db_session, query_vector, k=2)

    assert results[0][0].content == "close"
    assert results[0][1] < results[1][1]

    db_session.delete(close_chunk)
    db_session.delete(far_chunk)
    db_session.delete(document)
    db_session.commit()