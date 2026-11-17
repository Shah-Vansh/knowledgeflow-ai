from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    LargeBinary,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.db.base import Base
from app.core.config import settings


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)  # stored lowercase
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Bumped by "log out everywhere": tokens carrying an older version stop working
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class WorkspaceMember(Base):
    """Who may use a workspace, and how: viewer < editor < owner."""

    __tablename__ = "workspace_members"

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversations: Mapped[List["Conversation"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan", passive_deletes=True
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="processing")
    uploaded_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    deleted_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)
    # SHA-256 of the uploaded bytes: the same file can't be added to a workspace twice
    content_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, server_default=text("1"), index=True
    )

    # What multimodal ingestion did with this file (pages OCR'd, tables found, notes ...)
    ingest_report: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    chunks: Mapped[List["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(String, nullable=False)
    embedding: Mapped[list] = mapped_column(Vector(settings.EMBEDDING_DIM))
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    strategy: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    chunk_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    overlap: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # "text" | "table" | "ocr" (scanned page / image file) | "image_text" (text inside an embedded image)
    chunk_type: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'text'"))
    # mean OCR confidence (0-1) for chunks that came from OCR, otherwise NULL
    ocr_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Database-computed (GENERATED ALWAYS AS ... STORED): declared with Computed so
    # SQLAlchemy never tries to INSERT a value into it.
    search_vector: Mapped[Optional[str]] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', content)", persisted=True),
        nullable=True,
    )

    document: Mapped["Document"] = relationship(back_populates="chunks")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workspace: Mapped["Workspace"] = relationship(back_populates="conversations")
    messages: Mapped[List["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.id",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String, nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # assistant messages: the structured sources the answer was built from
    sources: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    # assistant messages: the standalone question actually searched (when the
    # follow-up was rewritten); None when the message was searched as typed
    standalone_question: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class Entity(Base):
    """
    A node of the knowledge graph, unique per workspace by normalized name.
    Entities are only ever created from text that literally contains the name
    (see app/rag/graph_extract.py), so every node has evidence in some chunk.
    """

    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("workspace_id", "normalized_name", name="uq_entities_workspace_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String, nullable=False, default="OTHER")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Relationship(Base):
    """
    A directed edge (source --relation--> target), always tied to the ONE chunk it
    was extracted from. Deleting that chunk (document deletion, rechunking) deletes
    the edge, so the graph can never point at evidence that no longer exists.
    """

    __tablename__ = "relationships"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_id: Mapped[int] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relation: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChunkEntity(Base):
    """Which entities a chunk mentions (used to pull evidence chunks for graph retrieval)."""

    __tablename__ = "chunk_entities"

    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    


class EvalSet(Base):
    """A golden set: questions with the evidence text that must be retrieved to answer them."""

    __tablename__ = "eval_sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvalQuestion(Base):
    """
    Relevance is defined by EVIDENCE TEXT, not chunk ids: a retrieved chunk counts as
    relevant when it contains one of the evidence snippets. Chunk ids change whenever a
    document is re-chunked, snippets don't, so one golden set can score any chunking.
    """

    __tablename__ = "eval_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    eval_set_id: Mapped[int] = mapped_column(
        ForeignKey("eval_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    reference_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    should_refuse: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    filename: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'manual'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Experiment(Base):
    """A named set of configuration variants to compare on one eval set."""

    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(primary_key=True)
    eval_set_id: Mapped[int] = mapped_column(
        ForeignKey("eval_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    variants: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    eval_set_id: Mapped[int] = mapped_column(
        ForeignKey("eval_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    experiment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), nullable=True, index=True
    )
    variant_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    label: Mapped[str] = mapped_column(String, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)           # "completed" | "failed"
    metrics: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    llm_calls: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    elapsed_ms: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvalResult(Base):
    __tablename__ = "eval_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[int] = mapped_column(
        ForeignKey("eval_questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    details: Mapped[dict] = mapped_column(JSONB, nullable=False)


class Job(Base):
    """
    A unit of background work (Phase 16). Workers claim queued jobs with
    SELECT ... FOR UPDATE SKIP LOCKED, so several workers never take the same job.
    """

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)               # "ingest"
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'queued'"))
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    file_data: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)  # cleared when done
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    locked_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
