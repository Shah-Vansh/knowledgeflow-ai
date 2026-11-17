"""Shared plumbing for the Phase 15 auth / access-control tests."""
import sys
import uuid
from dataclasses import dataclass, field
from typing import Dict, List

import pytest

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.db.models import (Chunk, Conversation, Document, EvalQuestion, EvalRun, EvalSet,
                           Experiment, Job, User, Workspace, WorkspaceMember)
from app.db.session import SessionLocal
from app.rag.experiments import validate_variants
from app.rag.llm import LLMProvider

PASSWORD = "correct-horse-battery-staple"


class FailingLLM(LLMProvider):
    """Access tests never need a real model: any call fails like an unreachable provider."""

    def __init__(self):
        self.calls: List[str] = []

    def generate(self, prompt, temperature=0.2):
        self.calls.append(prompt)
        raise RuntimeError("no LLM in access-control tests")


@pytest.fixture
def no_llm(monkeypatch):
    llm = FailingLLM()
    for name, module in list(sys.modules.items()):
        if name.startswith("app.") and hasattr(module, "get_llm_provider"):
            monkeypatch.setattr(module, "get_llm_provider", lambda: llm)
    return llm


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    yield


def bearer(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def delete_users(db, emails) -> None:
    if emails:
        db.query(User).filter(User.email.in_(list(emails))).delete(synchronize_session=False)


def delete_workspaces(db, ids) -> None:
    ids = list(ids)
    if not ids:
        return
    doc_ids = [r[0] for r in db.query(Document.id).filter(Document.workspace_id.in_(ids)).all()]
    if doc_ids:
        db.query(Chunk).filter(Chunk.document_id.in_(doc_ids)).delete(synchronize_session=False)
        db.query(Document).filter(Document.id.in_(doc_ids)).delete(synchronize_session=False)
    db.query(Workspace).filter(Workspace.id.in_(ids)).delete(synchronize_session=False)


@dataclass
class World:
    prefix: str
    ws: Dict[str, int] = field(default_factory=dict)
    users: Dict[str, dict] = field(default_factory=dict)     # actor -> {id, email, token}
    res: Dict[str, Dict[str, int]] = field(default_factory=dict)  # "A"/"B" -> kind -> id

    def headers(self, actor: str) -> Dict[str, str]:
        if actor == "anon":
            return {}
        return bearer(self.users[actor]["token"])


def _make_user(db, email: str) -> dict:
    user = User(email=email, password_hash=hash_password(PASSWORD), is_active=True)
    db.add(user)
    db.flush()
    return {"id": user.id, "email": email, "token": create_access_token(user.id, email)}


def _make_resources(db, workspace_id: int, tag: str) -> Dict[str, int]:
    doc = Document(filename=f"{tag}.txt", status="ready", workspace_id=workspace_id,
                   raw_text=f"{tag} text", source_type="txt")
    conv = Conversation(workspace_id=workspace_id, title=f"{tag} chat")
    eval_set = EvalSet(workspace_id=workspace_id, name=f"{tag} set")
    db.add_all([doc, conv, eval_set])
    db.flush()
    question = EvalQuestion(eval_set_id=eval_set.id, question=f"What is in {tag}?",
                            evidence=[f"{tag} text"], source="manual")
    run = EvalRun(eval_set_id=eval_set.id, label=f"{tag} run", config={}, status="completed",
                  metrics={}, question_count=0)
    experiment = Experiment(eval_set_id=eval_set.id, name=f"{tag} experiment",
                            variants=validate_variants([{"label": "base"}]))
    job = Job(kind="ingest", status="succeeded", workspace_id=workspace_id, document_id=doc.id,
              payload={}, attempts=1, max_attempts=3)
    db.add_all([question, run, experiment, job])
    db.flush()
    return {"document": doc.id, "conversation": conv.id, "eval_set": eval_set.id,
            "eval_question": question.id, "eval_run": run.id, "experiment": experiment.id,
            "job": job.id}


@pytest.fixture
def world():
    """
    Workspace A: owner, viewer.   Workspace B: other (owner of B only).
    nonmember: a valid user with no workspaces.   Every resource kind exists in A and B.
    """
    prefix = f"acl-{uuid.uuid4().hex[:8]}"
    w = World(prefix=prefix)
    db = SessionLocal()
    try:
        for key in ("A", "B"):
            workspace = Workspace(name=f"{prefix}-{key}")
            db.add(workspace)
            db.flush()
            w.ws[key] = workspace.id
        for actor in ("owner", "viewer", "other", "nonmember", "spare"):
            w.users[actor] = _make_user(db, f"{actor}@{prefix}.example.com")
        db.add_all([
            WorkspaceMember(workspace_id=w.ws["A"], user_id=w.users["owner"]["id"], role="owner"),
            WorkspaceMember(workspace_id=w.ws["A"], user_id=w.users["viewer"]["id"], role="viewer"),
            WorkspaceMember(workspace_id=w.ws["B"], user_id=w.users["other"]["id"], role="owner"),
        ])
        for key in ("A", "B"):
            w.res[key] = _make_resources(db, w.ws[key], f"{prefix}-{key}")
        db.commit()
    finally:
        db.close()

    yield w

    db = SessionLocal()
    try:
        created = [r[0] for r in db.query(Workspace.id).filter(Workspace.name.like(f"{prefix}%")).all()]
        delete_workspaces(db, created)
        db.query(User).filter(User.email.like(f"%@{prefix}.example.com")).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
