import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.models import Chunk, Document, Workspace
from app.db.session import SessionLocal
from app.main import app
from app.rag.embeddings import get_embedding_provider
from app.rag.llm import LLMProvider
from app.rag.pipeline import NO_INFO_RESPONSE, answer_question, ingest_document
from app.rag.reranker import Reranker
from app.rag.retriever import (
    retrieve_bm25,
    retrieve_bm25_any_term,
    retrieve_hybrid,
    retrieve_top_k,
)

client = TestClient(app)


class NoopReranker(Reranker):
    def score(self, query, passages):
        return [0.0] * len(passages)


class ForbiddenLLM(LLMProvider):
    """Any call is a test failure — used where the pipeline must refuse without the LLM."""

    def generate(self, prompt, temperature=0.2):
        raise AssertionError("the LLM must not be called")


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def track():
    """Collects workspace ids created by a test; removes them and everything in them afterwards."""
    ids = []
    yield ids

    session = SessionLocal()
    try:
        if ids:
            doc_ids = [r[0] for r in session.query(Document.id).filter(Document.workspace_id.in_(ids)).all()]
            if doc_ids:
                session.query(Chunk).filter(Chunk.document_id.in_(doc_ids)).delete(synchronize_session=False)
                session.query(Document).filter(Document.id.in_(doc_ids)).delete(synchronize_session=False)
            # conversations and messages go with their workspace (ON DELETE CASCADE)
            session.query(Workspace).filter(Workspace.id.in_(ids)).delete(synchronize_session=False)
            session.commit()
    finally:
        session.close()


def _make_workspace(track, label="ws"):
    response = client.post("/workspaces", json={"name": f"test-{label}-{uuid.uuid4().hex[:8]}"})
    assert response.status_code == 201
    workspace_id = response.json()["id"]
    track.append(workspace_id)
    return workspace_id


def _upload(workspace_id, name, text):
    response = client.post(
        "/documents/upload",
        files={"file": (name, text.encode(), "text/plain")},
        data={"workspace_id": str(workspace_id)},
    )
    return response


# ---------- workspace CRUD ----------

def test_default_workspace_exists():
    response = client.get("/workspaces")
    assert response.status_code == 200
    general = [w for w in response.json() if w["id"] == 1]
    assert general and general[0]["name"] == "General"


def test_create_workspace_rejects_duplicates_and_blank_names(track):
    name = f"test-dup-{uuid.uuid4().hex[:8]}"
    created = client.post("/workspaces", json={"name": name, "description": "  desc  "})
    assert created.status_code == 201
    track.append(created.json()["id"])
    assert created.json()["description"] == "desc"
    assert created.json()["document_count"] == 0

    assert client.post("/workspaces", json={"name": name.upper()}).status_code == 409
    assert client.post("/workspaces", json={"name": "   "}).status_code == 422
    assert client.post("/workspaces", json={"name": ""}).status_code == 422


def test_cannot_delete_default_workspace():
    assert client.delete("/workspaces/1").status_code == 400


def test_delete_workspace_rules(track):
    workspace_id = _make_workspace(track)

    # non-empty workspace cannot be deleted
    upload = _upload(workspace_id, "d.txt", "Some content about gardening and plants.")
    assert upload.status_code == 200
    document_id = upload.json()["document_id"]
    blocked = client.delete(f"/workspaces/{workspace_id}")
    assert blocked.status_code == 409

    # a soft-deleted document no longer blocks deletion
    assert client.delete(f"/documents/{document_id}").status_code == 200
    assert client.delete(f"/workspaces/{workspace_id}").status_code == 200
    assert client.delete(f"/workspaces/{workspace_id}").status_code == 404
    ids = [w["id"] for w in client.get("/workspaces").json()]
    assert workspace_id not in ids


# ---------- documents belong to workspaces ----------

def test_upload_lands_in_workspace_and_lists_are_filtered(track):
    a = _make_workspace(track, "a")
    b = _make_workspace(track, "b")

    upload = _upload(a, "only_in_a.txt", "Apples grow on trees in the orchard.")
    assert upload.status_code == 200
    assert upload.json()["workspace_id"] == a

    in_a = [d["filename"] for d in client.get(f"/documents?workspace_id={a}").json()]
    in_b = [d["filename"] for d in client.get(f"/documents?workspace_id={b}").json()]
    assert in_a == ["only_in_a.txt"]
    assert in_b == []

    counts = {w["id"]: w["document_count"] for w in client.get("/workspaces").json()}
    assert counts[a] == 1 and counts[b] == 0


def test_upload_to_missing_workspace_is_404():
    response = _upload(999999, "x.txt", "text")
    assert response.status_code == 404


def test_default_upload_goes_to_general_workspace():
    response = client.post(
        "/documents/upload", files={"file": ("general_default.txt", b"Default workspace content here.", "text/plain")}
    )
    assert response.status_code == 200
    assert response.json()["workspace_id"] == 1
    client.delete(f"/documents/{response.json()['document_id']}")


# ---------- retrieval isolation (enforced in SQL) ----------

def test_retrieval_is_isolated_by_workspace(db_session, tmp_path, track):
    a = _make_workspace(track, "a")
    b = _make_workspace(track, "b")
    empty = _make_workspace(track, "empty")

    file_a = tmp_path / "a.txt"
    file_a.write_text("Apples grow on trees in the orchard.")
    file_b = tmp_path / "b.txt"
    file_b.write_text("Bananas grow on plants in the tropics.")
    doc_a = ingest_document(db_session, str(file_a), "a.txt", workspace_id=a)
    doc_b = ingest_document(db_session, str(file_b), "b.txt", workspace_id=b)

    vec = get_embedding_provider().embed("Bananas")

    # dense: only this workspace's chunks, even though the query is about bananas
    dense_a = retrieve_top_k(db_session, vec, k=10, workspace_id=a)
    assert dense_a and all(chunk.document_id == doc_a.id for chunk, _ in dense_a)
    dense_b = retrieve_top_k(db_session, vec, k=10, workspace_id=b)
    assert dense_b and all(chunk.document_id == doc_b.id for chunk, _ in dense_b)

    # sparse: the keyword exists only in workspace b
    assert retrieve_bm25(db_session, "Bananas", k=10, workspace_id=a) == []
    assert len(retrieve_bm25(db_session, "Bananas", k=10, workspace_id=b)) == 1
    assert retrieve_bm25_any_term(db_session, ["Bananas"], k=10, workspace_id=a) == []

    # hybrid
    hybrid = retrieve_hybrid(db_session, "Bananas", vec, k=5, workspace_id=a)
    assert hybrid["fused"] and all(chunk.document_id == doc_a.id for chunk, _ in hybrid["fused"])
    assert hybrid["sparse_hit_count"] == 0

    # an EMPTY workspace must return nothing — never fall back to "search everything"
    assert retrieve_top_k(db_session, vec, k=10, workspace_id=empty) == []
    assert retrieve_bm25(db_session, "Bananas", k=10, workspace_id=empty) == []
    assert retrieve_hybrid(db_session, "Bananas", vec, k=5, workspace_id=empty)["fused"] == []

    # an explicit document filter cannot reach across workspaces either
    crossed = retrieve_top_k(db_session, vec, k=10, document_ids=[doc_b.id], workspace_id=a)
    assert crossed == []


def test_answer_question_refuses_in_empty_workspace_without_llm(db_session, track, monkeypatch):
    monkeypatch.setattr(settings, "RERANK_ENABLED", False)
    empty = _make_workspace(track, "empty")

    result = answer_question(
        db_session, "Tell me about bananas", workspace_id=empty,
        reranker=NoopReranker(), llm=ForbiddenLLM(),
    )
    assert result["answer"] == NO_INFO_RESPONSE
    assert result["sources"] == []


def test_query_endpoints_respect_workspace(track):
    a = _make_workspace(track, "a")
    b = _make_workspace(track, "b")
    assert _upload(b, "only_b.txt", "Bananas grow on plants in the tropics.").status_code == 200

    base = {"question": "Bananas", "mode": "sparse", "k": 5}
    in_a = client.post("/query/retrieve", json={**base, "workspace_id": a})
    in_b = client.post("/query/retrieve", json={**base, "workspace_id": b})
    assert in_a.status_code == 200 and in_a.json()["results"] == []
    assert len(in_b.json()["results"]) == 1

    assert client.post("/query/retrieve", json={**base, "workspace_id": 999999}).status_code == 404
    assert client.post("/query", json={"question": "Bananas", "workspace_id": 999999}).status_code == 404