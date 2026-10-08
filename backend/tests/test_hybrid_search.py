import pytest

from app.db.session import SessionLocal
from app.db.models import Chunk
from app.rag.pipeline import ingest_document
from app.rag.retriever import (
    retrieve_top_k,
    retrieve_bm25,
    retrieve_hybrid,
    reciprocal_rank_fusion,
)
from app.rag.embeddings import get_embedding_provider


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def seeded_document(db_session, tmp_path):
    file_path = tmp_path / "hybrid_sample.txt"
    file_path.write_text(
        "Employee badge number X7Q92 grants access to the server room. "
        "Our machine learning model was trained on a large text dataset. "
        "The quarterly budget meeting is scheduled for next Tuesday."
    )
    # sentence strategy + small chunk_size => exactly one chunk per sentence (3 chunks)
    document = ingest_document(
        db_session, str(file_path), "hybrid_sample.txt",
        strategy="sentence", chunk_size=80, overlap=0,
    )
    yield document

    db_session.query(Chunk).filter(Chunk.document_id == document.id).delete()
    db_session.delete(document)
    db_session.commit()


def test_sparse_finds_exact_rare_term(seeded_document, db_session):
    results = retrieve_bm25(db_session, "X7Q92", k=5, document_ids=[seeded_document.id])
    assert len(results) > 0
    assert "X7Q92" in results[0][0].content


def test_dense_finds_semantic_paraphrase(seeded_document, db_session):
    embedder = get_embedding_provider()
    query_vector = embedder.embed("AI software that learns from data")
    results = retrieve_top_k(db_session, query_vector, k=3, document_ids=[seeded_document.id])
    assert len(results) > 0
    assert "machine learning" in results[0][0].content


def test_rrf_boosts_chunk_found_in_both_lists(seeded_document, db_session):
    chunks = (
        db_session.query(Chunk)
        .filter(Chunk.document_id == seeded_document.id)
        .order_by(Chunk.chunk_index)
        .all()
    )
    assert len(chunks) == 3
    shared_chunk = chunks[0]
    dense_only_chunk = chunks[1]

    dense_results = [(shared_chunk, 0.3), (dense_only_chunk, 0.5)]
    sparse_results = [(shared_chunk, 0.9)]

    fused = reciprocal_rank_fusion(dense_results, sparse_results, rrf_k=60, top_k=5)
    fused_ids_in_order = [chunk.id for chunk, _ in fused]

    assert fused_ids_in_order[0] == shared_chunk.id


def test_hybrid_surfaces_exact_term_match(seeded_document, db_session):
    embedder = get_embedding_provider()
    query_vector = embedder.embed("X7Q92")

    result = retrieve_hybrid(
        db_session, "X7Q92", query_vector, k=3, document_ids=[seeded_document.id]
    )
    assert result["sparse_hit_count"] >= 1
    assert "X7Q92" in result["fused"][0][0].content


def test_retrieve_hybrid_respects_k_and_document_ids(seeded_document, db_session):
    embedder = get_embedding_provider()
    query_vector = embedder.embed("budget meeting")

    result = retrieve_hybrid(
        db_session, "budget meeting", query_vector, k=1, document_ids=[seeded_document.id]
    )
    assert len(result["fused"]) <= 1
    for chunk, _ in result["fused"]:
        assert chunk.document_id == seeded_document.id