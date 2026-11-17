import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.evaluation import _run_dict
from app.core.access import current_user
from app.db.models import EvalSet, Experiment, WorkspaceMember
from app.rag.experiments import build_comparison, run_variant, validate_variants
from app.rag.evaluation import EvalConfig
from app.rag.llm import get_llm_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/experiments", tags=["experiments"])


class ExperimentCreate(BaseModel):
    eval_set_id: int
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)
    variants: List[Dict[str, Any]]


class RunVariantRequest(BaseModel):
    index: int = Field(ge=0)


def _get_experiment(db: Session, experiment_id: int) -> Experiment:
    experiment = db.get(Experiment, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return experiment


@router.post("", status_code=201)
def create_experiment(request: ExperimentCreate, db: Session = Depends(get_db)):
    if db.get(EvalSet, request.eval_set_id) is None:
        raise HTTPException(status_code=404, detail="Eval set not found")
    try:
        variants = validate_variants(request.variants)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    experiment = Experiment(
        eval_set_id=request.eval_set_id, name=" ".join(request.name.split()),
        description=(request.description or "").strip() or None, variants=variants,
    )
    db.add(experiment)
    db.commit()
    db.refresh(experiment)
    return build_comparison(db, experiment)


@router.get("")
def list_experiments(request: Request, db: Session = Depends(get_db)):
    query = db.query(Experiment)
    user = current_user(request)
    if user is not None:  # auth on: only experiments on eval sets of the caller's workspaces
        query = (
            query.join(EvalSet, EvalSet.id == Experiment.eval_set_id)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == EvalSet.workspace_id)
            .filter(WorkspaceMember.user_id == user.id)
        )
    experiments = query.order_by(Experiment.id.desc()).all()
    return [
        {"id": e.id, "name": e.name, "eval_set_id": e.eval_set_id, "variant_count": len(e.variants),
         "created_at": e.created_at.isoformat() if e.created_at else None}
        for e in experiments
    ]


@router.get("/{experiment_id}")
def get_experiment(experiment_id: int, db: Session = Depends(get_db)):
    return build_comparison(db, _get_experiment(db, experiment_id))


@router.delete("/{experiment_id}")
def delete_experiment(experiment_id: int, db: Session = Depends(get_db)):
    experiment = _get_experiment(db, experiment_id)
    db.delete(experiment)
    db.commit()
    return {"experiment_id": experiment_id, "deleted": True}


@router.post("/{experiment_id}/run-variant")
def run_one_variant(experiment_id: int, request: RunVariantRequest, db: Session = Depends(get_db)):
    """
    Runs ONE variant (the UI calls this once per variant so progress is visible and a
    failure only costs that variant). Variants that re-chunk take longer: the documents
    are chunked and embedded again into a temporary workspace.
    """
    experiment = _get_experiment(db, experiment_id)
    if request.index >= len(experiment.variants):
        raise HTTPException(status_code=422, detail="Variant index out of range")

    config = EvalConfig.from_dict(experiment.variants[request.index])
    llm = get_llm_provider() if (config.generate or config.transforms) else None
    try:
        run = run_variant(db, experiment, request.index, llm=llm)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _run_dict(run)