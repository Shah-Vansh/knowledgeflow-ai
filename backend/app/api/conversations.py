import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import DEFAULT_WORKSPACE_ID, get_db, require_workspace
from app.db.models import Conversation, Message
from app.rag.conversation import MAX_HISTORY_MESSAGES, contextualize_question
from app.rag.llm import get_llm_provider
from app.rag.pipeline import answer_question
from app.rag.query_transform import normalize_transforms

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])

DEFAULT_TITLE = "New conversation"


class ConversationCreate(BaseModel):
    workspace_id: int = DEFAULT_WORKSPACE_ID
    title: Optional[str] = Field(default=None, max_length=120)


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    transforms: Optional[List[str]] = None  # None = server default (QUERY_TRANSFORMS)


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def _conversation_dict(conversation: Conversation, message_count: Optional[int] = None) -> dict:
    data = {
        "id": conversation.id,
        "workspace_id": conversation.workspace_id,
        "title": conversation.title,
        "created_at": _iso(conversation.created_at),
        "updated_at": _iso(conversation.updated_at),
    }
    if message_count is not None:
        data["message_count"] = message_count
    return data


def _message_dict(message: Message) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "sources": message.sources or [],
        "standalone_question": message.standalone_question,
        "created_at": _iso(message.created_at),
    }


def _get_conversation(db: Session, conversation_id: int) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.post("", status_code=201)
def create_conversation(request: ConversationCreate, db: Session = Depends(get_db)):
    workspace = require_workspace(db, request.workspace_id)
    title = " ".join((request.title or "").split()) or DEFAULT_TITLE

    conversation = Conversation(workspace_id=workspace.id, title=title)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return _conversation_dict(conversation, message_count=0)


@router.get("")
def list_conversations(workspace_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(Conversation, func.count(Message.id)).outerjoin(
        Message, Message.conversation_id == Conversation.id
    )
    if workspace_id is not None:
        query = query.filter(Conversation.workspace_id == workspace_id)

    rows = (
        query.group_by(Conversation.id)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .all()
    )
    return [_conversation_dict(conversation, count) for conversation, count in rows]


@router.get("/{conversation_id}")
def get_conversation(conversation_id: int, db: Session = Depends(get_db)):
    conversation = _get_conversation(db, conversation_id)
    data = _conversation_dict(conversation)
    data["messages"] = [_message_dict(m) for m in conversation.messages]
    return data


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: int, db: Session = Depends(get_db)):
    conversation = _get_conversation(db, conversation_id)
    db.delete(conversation)
    db.commit()
    return {"conversation_id": conversation_id, "deleted": True}


@router.post("/{conversation_id}/messages")
def send_message(conversation_id: int, request: MessageCreate, db: Session = Depends(get_db)):
    """
    One conversational turn: (1) resolve the follow-up into a standalone question
    using recent history, (2) answer it with the normal RAG pipeline, restricted to
    this conversation's workspace, (3) store both messages with the sources used.
    Nothing is stored if answering fails.
    """
    conversation = _get_conversation(db, conversation_id)

    content = request.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Message must not be empty")

    transforms = None
    if request.transforms is not None:
        try:
            transforms = normalize_transforms(request.transforms)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    recent = (
        db.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .order_by(Message.id.desc())
        .limit(MAX_HISTORY_MESSAGES)
        .all()
    )
    history = [{"role": m.role, "content": m.content} for m in reversed(recent)]

    llm = get_llm_provider()
    contextual = contextualize_question(llm, history, content)

    try:
        result = answer_question(
            db,
            contextual.standalone,
            workspace_id=conversation.workspace_id,
            transforms=transforms,
            llm=llm,
        )
    except Exception:
        logger.exception("Answering failed for conversation %s", conversation.id)
        db.rollback()
        raise HTTPException(
            status_code=502,
            detail="Answering failed (the language model or search backend returned an error). "
                   "Nothing was saved; please try again.",
        )

    user_message = Message(conversation_id=conversation.id, role="user", content=content)
    db.add(user_message)
    db.flush()  # user message gets the lower id

    assistant_message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=result["answer"],
        sources=result["sources"],
        standalone_question=contextual.standalone if contextual.rewritten else None,
    )
    db.add(assistant_message)

    if conversation.title == DEFAULT_TITLE and not history:
        conversation.title = " ".join(content.split())[:60]
    conversation.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(user_message)
    db.refresh(assistant_message)

    return {
        "user_message": _message_dict(user_message),
        "assistant_message": _message_dict(assistant_message),
        "standalone_question": contextual.standalone,
        "contextualized": contextual.rewritten,
        "contextualize_fallback": contextual.fallback_used,
        "transforms_used": result.get("transforms_used", []),
        "transformation_fallback": result.get("transformation_fallback", False),
        "conversation_title": conversation.title,
    }