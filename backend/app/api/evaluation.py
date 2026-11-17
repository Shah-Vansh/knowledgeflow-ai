import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import DEFAULT_WORKSPACE_ID, get_db, require_workspace
from app.db.models import EvalQuestion, EvalResult, EvalRun, EvalSet
from app.rag.evaluation import (
    MAX_QUESTIONS_PER_SET,
    EvalConfig,
    clean_evidence,
    generate_questions,
    normalize_for_match,
    run_evaluation,
)
from app.rag.llm import get_llm_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/eval", tags=["evaluation"])


class SetCreate(BaseModel):
    workspace_id: int = DEFAULT_WORKSPACE_ID
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)


class QuestionCreate(BaseModel):
    question: str = Field(min_length=5, max_length=500)
    evidence: List[str] = Field(default_factory=list)
    reference_answer: Optional[str] = Field(default=None, max_length=1000)
    should_refuse: bool = False
    filename: Optional[str] = Field(default=None, max_length=255)


class GenerateRequest(BaseModel):
    count: int = Field(default=10, ge=1, le=20)
    seed: int = 0


class RunRequest(BaseModel):
    eval_set_id: int
    label: Optional[str] = Field(default=None, max_length=120)
    config: Dict[str, Any] = Field(default_factory=dict)


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def _question_dict(q: EvalQuestion) -> dict:
    return {
        "id": q.id,
        "question": q.question,
        "evidence": q.evidence or [],
        "reference_answer": q.reference_answer,
        "should_refuse": q.should_refuse,
        "filename": q.filename,
        "source": q.source,
    }


def _run_dict(run: EvalRun) -> dict:
    return {
        "id": run.id,
        "eval_set_id": run.eval_set_id,
        "experiment_id": run.experiment_id,
        "variant_index": run.variant_index,
        "label": run.label,
        "config": run.config,
        "status": run.status,
        "metrics": run.metrics,
        "question_count": run.question_count,
        "llm_calls": run.llm_calls,
        "elapsed_ms": run.elapsed_ms,
        "error": run.error,
        "created_at": _iso(run.created_at),
    }


def _get_set(db: Session, set_id: int) -> EvalSet:
    eval_set = db.get(EvalSet, set_id)
    if eval_set is None:
        raise HTTPException(status_code=404, detail="Eval set not found")
    return eval_set


# ------------------------------------------------------------------- sets

@router.post("/sets", status_code=201)
def create_set(request: SetCreate, db: Session = Depends(get_db)):
    require_workspace(db, request.workspace_id)
    name = " ".join(request.name.split())
    if not name:
        raise HTTPException(status_code=422, detail="Name must not be empty")
    eval_set = EvalSet(workspace_id=request.workspace_id, name=name, description=(request.description or "").strip() or None)
    db.add(eval_set)
    db.commit()
    db.refresh(eval_set)
    return {"id": eval_set.id, "workspace_id": eval_set.workspace_id, "name": eval_set.name,
            "description": eval_set.description, "question_count": 0, "created_at": _iso(eval_set.created_at)}


@router.get("/sets")
def list_sets(workspace_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    query = db.query(EvalSet, func.count(EvalQuestion.id)).outerjoin(EvalQuestion, EvalQuestion.eval_set_id == EvalSet.id)
    if workspace_id is not None:
        query = query.filter(EvalSet.workspace_id == workspace_id)
    rows = query.group_by(EvalSet.id).order_by(EvalSet.id.desc()).all()
    return [
        {"id": s.id, "workspace_id": s.workspace_id, "name": s.name, "description": s.description,
         "question_count": count, "created_at": _iso(s.created_at)}
        for s, count in rows
    ]


@router.get("/sets/{set_id}")
def get_set(set_id: int, db: Session = Depends(get_db)):
    eval_set = _get_set(db, set_id)
    questions = db.query(EvalQuestion).filter(EvalQuestion.eval_set_id == set_id).order_by(EvalQuestion.id).all()
    return {"id": eval_set.id, "workspace_id": eval_set.workspace_id, "name": eval_set.name,
            "description": eval_set.description, "questions": [_question_dict(q) for q in questions]}


@router.delete("/sets/{set_id}")
def delete_set(set_id: int, db: Session = Depends(get_db)):
    eval_set = _get_set(db, set_id)
    db.delete(eval_set)
    db.commit()
    return {"set_id": set_id, "deleted": True}


# -------------------------------------------------------------- questions

@router.post("/sets/{set_id}/questions", status_code=201)
def add_question(set_id: int, request: QuestionCreate, db: Session = Depends(get_db)):
    eval_set = _get_set(db, set_id)
    question = " ".join(request.question.split())

    try:
        evidence = clean_evidence(request.evidence)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if request.should_refuse and evidence:
        raise HTTPException(status_code=422, detail="A question that should be refused has no evidence")
    if not request.should_refuse and not evidence:
        raise HTTPException(status_code=422, detail="Give at least one evidence snippet, or mark the question as should-refuse")

    existing = db.query(EvalQuestion).filter(EvalQuestion.eval_set_id == set_id).all()
    if len(existing) >= MAX_QUESTIONS_PER_SET:
        raise HTTPException(status_code=422, detail=f"A set can hold at most {MAX_QUESTIONS_PER_SET} questions")
    if normalize_for_match(question) in {normalize_for_match(q.question) for q in existing}:
        raise HTTPException(status_code=409, detail="This question is already in the set")

    created = EvalQuestion(
        eval_set_id=eval_set.id, question=question, evidence=evidence,
        reference_answer=(request.reference_answer or "").strip() or None,
        should_refuse=request.should_refuse,
        filename=(request.filename or "").strip() or None,
        source="manual",
    )
    db.add(created)
    db.commit()
    db.refresh(created)
    return _question_dict(created)


@router.delete("/questions/{question_id}")
def delete_question(question_id: int, db: Session = Depends(get_db)):
    question = db.get(EvalQuestion, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    db.delete(question)
    db.commit()
    return {"question_id": question_id, "deleted": True}


@router.post("/sets/{set_id}/generate")
def generate(set_id: int, request: GenerateRequest, db: Session = Depends(get_db)):
    """Drafts questions from the workspace's chunks. Costs about count/4 LLM calls."""
    eval_set = _get_set(db, set_id)
    try:
        return generate_questions(db, eval_set, get_llm_provider(), count=request.count, seed=request.seed)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ------------------------------------------------------------------- runs

@router.post("/runs")
def create_run(request: RunRequest, db: Session = Depends(get_db)):
    """Scores one configuration on every question of a set. Retrieval-only runs make no LLM calls."""
    eval_set = _get_set(db, request.eval_set_id)
    try:
        config = EvalConfig.from_dict(request.config)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    llm = get_llm_provider() if (config.generate or config.transforms) else None
    try:
        run = run_evaluation(db, eval_set, config, llm=llm, label=request.label)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _run_dict(run)


@router.get("/runs")
def list_runs(eval_set_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    query = db.query(EvalRun)
    if eval_set_id is not None:
        query = query.filter(EvalRun.eval_set_id == eval_set_id)
    return [_run_dict(r) for r in query.order_by(EvalRun.id.desc()).limit(100).all()]


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    results = db.query(EvalResult).filter(EvalResult.run_id == run_id).order_by(EvalResult.id).all()
    return {**_run_dict(run), "results": [{"question_id": r.question_id, **r.details} for r in results]}


@router.delete("/runs/{run_id}")
def delete_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    db.delete(run)
    db.commit()
    return {"run_id": run_id, "deleted": True}