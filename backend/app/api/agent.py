import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent.workflow import run_agent
from app.api.deps import DEFAULT_WORKSPACE_ID, get_db, require_workspace
from app.rag.llm import get_llm_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    workspace_id: int = DEFAULT_WORKSPACE_ID


@router.post("/query")
def agent_query(request: AgentRequest, db: Session = Depends(get_db)):
    """
    Routes the question to the right tool (rag, graph, document_search, metadata,
    calculator) and returns the answer with the route taken and a step trace.
    Always scoped to one workspace.
    """
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Question must not be empty")
    require_workspace(db, request.workspace_id)

    try:
        return run_agent(db, question, request.workspace_id, get_llm_provider())
    except Exception:
        logger.exception("Agent failed")
        db.rollback()
        raise HTTPException(
            status_code=502,
            detail="The agent failed (the language model or search backend returned an error).",
        )