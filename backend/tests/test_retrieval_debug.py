import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.session import SessionLocal
from app.db.models import Chunk
from app.rag.pipeline import ingest_document

client = TestClient(app)


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def seeded_document(db_session, tmp_path):
    file_path = tmp_path / "retrieval_debug_sample.txt"
    file_path.write_text(
        "The company's refund policy allows returns within 30 days. "
        "Our headquarters is located in Berlin, Germany. "
        "The product warranty lasts for two full years after purchase."
    )
    document = ingest_document(db_session, str(file_path), "retrieval_debug_sample.txt")
    yield document

    db_session.query(Chunk).filter(Chunk.document_id == document.id).delete()
    db_session.delete(document)
    db_session.commit()


def test_retrieve_debug_dense_orders_by_ascending_distance(seeded_document):
    response = client.post(
        "/query/retrieve",
        json={"question": "What is the refund policy?", "k": 5, "mode": "dense"},
    )
    assert response.status_code == 200
    body = response.json()
    distances = [r["dense_distance"] for r in body["results"]]
    assert len(distances) > 0
    assert distances == sorted(distances)


def test_retrieve_debug_respects_k_limit(seeded_document):
    response = client.post("/query/retrieve", json={"question": "warranty", "k": 1})
    body = response.json()
    assert len(body["results"]) <= 1
    assert body["k_used"] == 1
    assert body["mode"] == "hybrid"  # default mode


def test_retrieve_debug_dense_strict_threshold_flags_nothing(seeded_document):
    # above_threshold is only meaningful in dense mode; hybrid/sparse always
    # report True because their results are already filtered/fused.
    response = client.post(
        "/query/retrieve",
        json={"question": "refund policy", "k": 5, "similarity_threshold": 0.001, "mode": "dense"},
    )
    body = response.json()
    assert len(body["results"]) > 0  # results are never hidden
    assert all(r["above_threshold"] is False for r in body["results"])


def test_retrieve_debug_document_ids_filter(seeded_document):
    other_document_id = seeded_document.id + 999999  # guaranteed not to exist
    response = client.post(
        "/query/retrieve",
        json={"question": "refund policy", "k": 5, "document_ids": [other_document_id]},
    )
    body = response.json()
    assert body["results"] == []


def test_retrieve_debug_sparse_mode_finds_exact_term(seeded_document):
    response = client.post(
        "/query/retrieve",
        json={"question": "Berlin", "k": 5, "mode": "sparse", "document_ids": [seeded_document.id]},
    )
    body = response.json()
    assert len(body["results"]) > 0
    for r in body["results"]:
        assert r["found_by"] == ["sparse"]
        assert r["sparse_score"] is not None
        assert r["dense_distance"] is None


def test_retrieve_debug_hybrid_reports_found_by(seeded_document):
    response = client.post(
        "/query/retrieve",
        json={"question": "Berlin", "k": 5, "mode": "hybrid", "document_ids": [seeded_document.id]},
    )
    body = response.json()
    assert len(body["results"]) > 0
    assert set(body["results"][0]["found_by"]) == {"dense", "sparse"}
    assert body["results"][0]["rrf_score"] is not None