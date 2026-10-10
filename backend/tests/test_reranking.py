from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.session import SessionLocal
from app.db.models import Chunk
from app.rag.pipeline import ingest_document, retrieve_context
from app.rag.reranker import Reranker, rerank_candidates
from app.rag.embeddings import get_embedding_provider

client = TestClient(app)


class MappingReranker(Reranker):
    """Scores passages from a fixed dict — lets us test ordering logic exactly."""

    def __init__(self, mapping):
        self.mapping = mapping

    def score(self, query, passages):
        return [self.mapping[p] for p in passages]


class ReverseReranker(Reranker):
    """Gives later candidates higher scores, so the input order is reversed."""

    def score(self, query, passages):
        return [float(i) for i in range(len(passages))]


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def seeded_document(db_session, tmp_path):
    file_path = tmp_path / "rerank_sample.txt"
    file_path.write_text(
        "The company's refund policy allows returns within 30 days. "
        "Our headquarters is located in Berlin, Germany. "
        "The product warranty lasts for two full years after purchase."
    )
    # sentence strategy + small chunk_size => one chunk per sentence (3 chunks)
    document = ingest_document(
        db_session, str(file_path), "rerank_sample.txt",
        strategy="sentence", chunk_size=80, overlap=0,
    )
    yield document

    db_session.query(Chunk).filter(Chunk.document_id == document.id).delete()
    db_session.delete(document)
    db_session.commit()


def test_rerank_candidates_reorders_and_truncates():
    a = SimpleNamespace(content="a", id=1)
    b = SimpleNamespace(content="b", id=2)
    c = SimpleNamespace(content="c", id=3)
    candidates = [(a, 0.03), (b, 0.02), (c, 0.01)]
    reranker = MappingReranker({"a": 0.1, "b": 0.9, "c": 0.5})

    result = rerank_candidates(reranker, "q", candidates, top_k=2)

    assert [item["chunk"].id for item in result] == [2, 3]
    assert [item["pre_rank"] for item in result] == [2, 3]
    assert [item["post_rank"] for item in result] == [1, 2]
    assert result[0]["fused_score"] == 0.02  # original fused score preserved


def test_rerank_candidates_empty_input():
    assert rerank_candidates(MappingReranker({}), "q", [], top_k=5) == []


def test_retrieve_context_with_fake_reranker_reverses_order(seeded_document, db_session):
    embedder = get_embedding_provider()
    query_vector = embedder.embed("anything")

    retrieval = retrieve_context(
        db_session, "anything", query_vector, k=2,
        document_ids=[seeded_document.id],
        reranker=ReverseReranker(), use_rerank=True,
    )

    assert retrieval["reranked"] is True
    ranked = retrieval["ranked"]
    candidate_count = len(retrieval["hybrid"]["fused"])
    assert candidate_count == 3

    assert len(ranked) == 2
    assert [item["post_rank"] for item in ranked] == [1, 2]
    # reversed scores => the last candidate becomes the top result
    assert ranked[0]["pre_rank"] == candidate_count


def test_retrieve_context_rerank_disabled_matches_phase5_behavior(seeded_document, db_session):
    embedder = get_embedding_provider()
    query_vector = embedder.embed("refund policy")

    retrieval = retrieve_context(
        db_session, "refund policy", query_vector, k=2,
        document_ids=[seeded_document.id], use_rerank=False,
    )

    assert retrieval["reranked"] is False
    assert len(retrieval["ranked"]) <= 2
    for item in retrieval["ranked"]:
        assert item["pre_rank"] == item["post_rank"]
        assert item["score"] == item["fused_score"]


def test_cross_encoder_puts_relevant_chunk_first(seeded_document, db_session):
    # Uses the REAL cross-encoder model (downloads ~90 MB on first run).
    embedder = get_embedding_provider()
    query_vector = embedder.embed("What is the refund policy?")

    retrieval = retrieve_context(
        db_session, "What is the refund policy?", query_vector, k=3,
        document_ids=[seeded_document.id], use_rerank=True,
    )

    assert retrieval["reranked"] is True
    assert "refund" in retrieval["ranked"][0]["chunk"].content


def test_debug_endpoint_reports_rerank_ranks(seeded_document, monkeypatch):
    monkeypatch.setattr("app.rag.pipeline.get_reranker", lambda: ReverseReranker())

    response = client.post(
        "/query/retrieve",
        json={
            "question": "refund policy",
            "k": 2,
            "mode": "hybrid",
            "rerank": True,
            "document_ids": [seeded_document.id],
        },
    )
    body = response.json()

    assert body["reranked"] is True
    assert len(body["results"]) == 2
    assert [r["post_rerank_rank"] for r in body["results"]] == [1, 2]
    for r in body["results"]:
        assert r["rerank_score"] is not None
        assert r["pre_rerank_rank"] is not None