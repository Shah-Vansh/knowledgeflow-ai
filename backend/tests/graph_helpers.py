"""Shared helpers for the Phase 11/12 tests (fake LLM, no-op reranker, workspace plumbing)."""
import json
import os
import tempfile
import uuid
from typing import List

from app.db.models import Chunk, Document, Workspace
from app.db.session import SessionLocal
from app.rag.llm import LLMProvider
from app.rag.pipeline import ingest_document
from app.rag.reranker import Reranker

# three sentences, each its own chunk with strategy="sentence", chunk_size=80
GRAPH_TEXT = (
    "RoBERTa is a transformer model that was developed by Meta AI. "
    "Streamlit provides the web interface used to run RoBERTa online. "
    "The AI Text Detector project was built by a team at LJ Institute."
)

# What a well-behaved model would return for the three chunks above, plus deliberate
# mistakes that validation must drop: an entity that is not in the text, a relation
# whose endpoint is not in the cited chunk, and a relation citing a chunk that doesn't exist.
GRAPH_EXTRACTION = json.dumps({
    "entities": [
        {"name": "RoBERTa", "type": "TECH"},
        {"name": "Meta AI", "type": "ORG"},
        {"name": "Streamlit", "type": "TECH"},
        {"name": "AI Text Detector", "type": "PRODUCT"},
        {"name": "LJ Institute", "type": "ORG"},
        {"name": "Quantum Banana", "type": "CONCEPT"},
    ],
    "relations": [
        {"source": "RoBERTa", "relation": "developed by", "target": "Meta AI", "chunk": 1},
        {"source": "Streamlit", "relation": "provides interface for", "target": "RoBERTa", "chunk": 2},
        {"source": "AI Text Detector", "relation": "built at", "target": "LJ Institute", "chunk": 3},
        {"source": "RoBERTa", "relation": "invented by", "target": "Streamlit", "chunk": 1},
        {"source": "RoBERTa", "relation": "uses", "target": "Quantum Banana", "chunk": 1},
        {"source": "RoBERTa", "relation": "x", "target": "Meta AI", "chunk": 9},
    ],
})


class FakeLLM(LLMProvider):
    """Plays back a script: each call returns the next string, or raises the next Exception."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: List[str] = []
        self.temperatures: List[float] = []

    def generate(self, prompt, temperature=0.2):
        self.calls.append(prompt)
        self.temperatures.append(temperature)
        if not self.script:
            raise AssertionError("unexpected extra LLM call")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class ForbiddenLLM(LLMProvider):
    """Any call is a test failure."""

    def generate(self, prompt, temperature=0.2):
        raise AssertionError("the LLM must not be called")


class NoopReranker(Reranker):
    def score(self, query, passages):
        return [0.0] * len(passages)


def make_workspace(session, ids: list, label: str = "ws") -> int:
    workspace = Workspace(name=f"test-{label}-{uuid.uuid4().hex[:8]}")
    session.add(workspace)
    session.commit()
    ids.append(workspace.id)
    return workspace.id


def ingest_text(session, workspace_id: int, filename: str, text: str, **kwargs) -> Document:
    kwargs.setdefault("strategy", "sentence")
    kwargs.setdefault("chunk_size", 80)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, filename)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        document = ingest_document(session, path, filename, workspace_id=workspace_id, **kwargs)
    assert document.status == "processed"
    return document


def cleanup_workspaces(ids: list) -> None:
    """Removes the workspaces a test created and everything inside them (graph rows cascade)."""
    if not ids:
        return
    session = SessionLocal()
    try:
        doc_ids = [r[0] for r in session.query(Document.id).filter(Document.workspace_id.in_(ids)).all()]
        if doc_ids:
            session.query(Chunk).filter(Chunk.document_id.in_(doc_ids)).delete(synchronize_session=False)
            session.query(Document).filter(Document.id.in_(doc_ids)).delete(synchronize_session=False)
        session.query(Workspace).filter(Workspace.id.in_(ids)).delete(synchronize_session=False)
        session.commit()
    finally:
        session.close()