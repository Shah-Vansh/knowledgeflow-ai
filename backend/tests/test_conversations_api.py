import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.models import Chunk, Document, Message, Workspace
from app.db.session import SessionLocal
from app.main import app
from app.rag.llm import LLMProvider
from app.rag.pipeline import NO_INFO_RESPONSE, ingest_document

client = TestClient(app)

DOC_TEXT = (
    "Transformers process whole sequences in parallel. "
    "The main advantage of transformers is that they capture long-range dependencies efficiently."
)


class FakeLLM(LLMProvider):
    """Plays back a script: each call returns the next string, or raises the next Exception."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def generate(self, prompt, temperature=0.2):
        self.calls.append(prompt)
        if not self.script:
            raise AssertionError("unexpected extra LLM call")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def workspaces():
    """Workspaces created by a test; they and everything in them are removed afterwards."""
    ids = []
    yield ids

    session = SessionLocal()
    try:
        if ids:
            doc_ids = [r[0] for r in session.query(Document.id).filter(Document.workspace_id.in_(ids)).all()]
            if doc_ids:
                session.query(Chunk).filter(Chunk.document_id.in_(doc_ids)).delete(synchronize_session=False)
                session.query(Document).filter(Document.id.in_(doc_ids)).delete(synchronize_session=False)
            session.query(Workspace).filter(Workspace.id.in_(ids)).delete(synchronize_session=False)
            session.commit()
    finally:
        session.close()


@pytest.fixture(autouse=True)
def fast_retrieval(monkeypatch):
    # no cross-encoder in these tests; the conversation logic is what's under test
    monkeypatch.setattr(settings, "RERANK_ENABLED", False)


def _workspace(workspaces, db_session, with_doc=True):
    response = client.post("/workspaces", json={"name": f"test-conv-{uuid.uuid4().hex[:8]}"})
    assert response.status_code == 201
    workspace_id = response.json()["id"]
    workspaces.append(workspace_id)

    if with_doc:
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "conv_doc.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(DOC_TEXT)
            document = ingest_document(db_session, path, "conv_doc.txt", workspace_id=workspace_id)
            assert document.status == "processed"
    return workspace_id


def _conversation(workspace_id):
    response = client.post("/conversations", json={"workspace_id": workspace_id})
    assert response.status_code == 201
    return response.json()["id"]


def _use_llm(monkeypatch, llm):
    monkeypatch.setattr("app.api.conversations.get_llm_provider", lambda: llm)


# ---------- the main behavior ----------

def test_followup_is_rewritten_and_answered_from_workspace(db_session, workspaces, monkeypatch):
    workspace_id = _workspace(workspaces, db_session)
    conversation_id = _conversation(workspace_id)

    rewritten = "What is the main advantage of transformers?"
    llm = FakeLLM([
        "Transformers are neural networks that process sequences in parallel.",  # answer, turn 1
        rewritten,                                                              # rewrite, turn 2
        "They capture long-range dependencies efficiently.",                    # answer, turn 2
    ])
    _use_llm(monkeypatch, llm)

    first = client.post(f"/conversations/{conversation_id}/messages", json={"content": "What are transformers?"})
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["contextualized"] is False            # no history yet -> no rewrite call
    assert first_body["assistant_message"]["content"].startswith("Transformers are neural networks")
    assert first_body["assistant_message"]["sources"][0]["filename"] == "conv_doc.txt"
    assert first_body["conversation_title"] == "What are transformers?"
    assert len(llm.calls) == 1

    second = client.post(f"/conversations/{conversation_id}/messages", json={"content": "What is their main advantage?"})
    assert second.status_code == 200
    body = second.json()
    assert body["contextualized"] is True
    assert body["standalone_question"] == rewritten
    assert body["assistant_message"]["standalone_question"] == rewritten
    assert body["assistant_message"]["content"] == "They capture long-range dependencies efficiently."
    assert body["assistant_message"]["sources"]

    assert len(llm.calls) == 3
    rewrite_prompt, answer_prompt = llm.calls[1], llm.calls[2]
    assert "What are transformers?" in rewrite_prompt           # history reached the rewrite
    assert "process sequences in parallel" in rewrite_prompt
    assert f"Question: {rewritten}" in answer_prompt            # the answer used the standalone question
    assert "their" not in answer_prompt.split("Question:")[1]

    stored = client.get(f"/conversations/{conversation_id}").json()
    assert [m["role"] for m in stored["messages"]] == ["user", "assistant", "user", "assistant"]
    assert stored["messages"][2]["content"] == "What is their main advantage?"   # stored as typed
    assert stored["messages"][3]["standalone_question"] == rewritten
    assert stored["title"] == "What are transformers?"


def test_rewrite_failure_falls_back_to_the_message_as_typed(db_session, workspaces, monkeypatch):
    workspace_id = _workspace(workspaces, db_session)
    conversation_id = _conversation(workspace_id)

    llm = FakeLLM(["First answer.", RuntimeError("boom"), "Second answer."])
    _use_llm(monkeypatch, llm)

    client.post(f"/conversations/{conversation_id}/messages", json={"content": "What are transformers?"})
    second = client.post(f"/conversations/{conversation_id}/messages", json={"content": "What is their main advantage?"})

    assert second.status_code == 200
    body = second.json()
    assert body["contextualize_fallback"] is True
    assert body["contextualized"] is False
    assert body["assistant_message"]["content"] == "Second answer."
    assert body["assistant_message"]["standalone_question"] is None


def test_refuses_without_llm_when_workspace_has_no_documents(db_session, workspaces, monkeypatch):
    # another workspace DOES contain matching content: it must stay invisible to this conversation
    _workspace(workspaces, db_session, with_doc=True)
    workspace_id = _workspace(workspaces, db_session, with_doc=False)
    conversation_id = _conversation(workspace_id)

    llm = FakeLLM([])   # any call raises
    _use_llm(monkeypatch, llm)

    response = client.post(f"/conversations/{conversation_id}/messages", json={"content": "What are transformers?"})
    assert response.status_code == 200
    body = response.json()
    assert body["assistant_message"]["content"] == NO_INFO_RESPONSE
    assert body["assistant_message"]["sources"] == []
    assert llm.calls == []
    assert len(client.get(f"/conversations/{conversation_id}").json()["messages"]) == 2


def test_answer_failure_returns_502_and_saves_nothing(db_session, workspaces, monkeypatch):
    workspace_id = _workspace(workspaces, db_session)
    conversation_id = _conversation(workspace_id)

    _use_llm(monkeypatch, FakeLLM([RuntimeError("model down")]))

    response = client.post(f"/conversations/{conversation_id}/messages", json={"content": "What are transformers?"})
    assert response.status_code == 502
    assert "Nothing was saved" in response.json()["detail"]
    assert client.get(f"/conversations/{conversation_id}").json()["messages"] == []


def test_history_window_is_limited(db_session, workspaces, monkeypatch):
    workspace_id = _workspace(workspaces, db_session)
    conversation_id = _conversation(workspace_id)

    # seed 10 old messages straight into the database
    session = SessionLocal()
    try:
        for i in range(10):
            session.add(Message(
                conversation_id=conversation_id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"old message number {i}",
            ))
        session.commit()
    finally:
        session.close()

    llm = FakeLLM(["What are transformers?", "An answer."])
    _use_llm(monkeypatch, llm)
    response = client.post(f"/conversations/{conversation_id}/messages", json={"content": "and that?"})
    assert response.status_code == 200

    rewrite_prompt = llm.calls[0]
    assert "old message number 9" in rewrite_prompt
    assert "old message number 4" in rewrite_prompt
    assert "old message number 3" not in rewrite_prompt        # only the last 6 messages


# ---------- CRUD and validation ----------

def test_conversation_crud_and_workspace_filtering(db_session, workspaces):
    a = _workspace(workspaces, db_session, with_doc=False)
    b = _workspace(workspaces, db_session, with_doc=False)
    conv_a = _conversation(a)
    _conversation(b)

    listed_a = client.get(f"/conversations?workspace_id={a}").json()
    assert [c["id"] for c in listed_a] == [conv_a]
    assert listed_a[0]["message_count"] == 0

    assert client.delete(f"/conversations/{conv_a}").status_code == 200
    assert client.get(f"/conversations/{conv_a}").status_code == 404
    assert client.delete(f"/conversations/{conv_a}").status_code == 404


def test_deleting_a_conversation_removes_its_messages(db_session, workspaces, monkeypatch):
    workspace_id = _workspace(workspaces, db_session)
    conversation_id = _conversation(workspace_id)
    _use_llm(monkeypatch, FakeLLM(["Answer."]))
    assert client.post(f"/conversations/{conversation_id}/messages", json={"content": "What are transformers?"}).status_code == 200

    assert client.delete(f"/conversations/{conversation_id}").status_code == 200
    session = SessionLocal()
    try:
        assert session.query(Message).filter(Message.conversation_id == conversation_id).count() == 0
    finally:
        session.close()


def test_validation_errors(db_session, workspaces, monkeypatch):
    workspace_id = _workspace(workspaces, db_session, with_doc=False)
    conversation_id = _conversation(workspace_id)
    _use_llm(monkeypatch, FakeLLM([]))

    assert client.post("/conversations", json={"workspace_id": 999999}).status_code == 404
    assert client.post("/conversations/999999/messages", json={"content": "hi"}).status_code == 404
    assert client.post(f"/conversations/{conversation_id}/messages", json={"content": ""}).status_code == 422
    assert client.post(f"/conversations/{conversation_id}/messages", json={"content": "   "}).status_code == 422
    bad = client.post(f"/conversations/{conversation_id}/messages", json={"content": "hi", "transforms": ["bogus"]})
    assert bad.status_code == 400
    assert "Allowed" in bad.json()["detail"]