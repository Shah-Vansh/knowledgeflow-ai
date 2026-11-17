"""
Experimentation lab (Phase 14): compare retrieval configurations on ONE eval set.

An experiment is a list of variants. The first variant is the baseline; every other one is
compared to it per question, with a paired bootstrap, so a difference is reported together
with how much it could be down to chance. With a small golden set most differences are NOT
significant, and saying so is the point.

A variant may also change the CHUNKING (strategy, size, overlap). That needs different
chunks, so the source workspace's stored document text is chunked and embedded into a
temporary workspace, evaluated there, and deleted again, leaving the real data untouched.
Page numbers and table structure are lost in that copy (it works from flat text).
"""
import logging
import random
import uuid
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models import Chunk, Document, EvalResult, EvalRun, EvalSet, Experiment, Workspace
from app.rag.chunker import chunk_text
from app.rag.embeddings import get_embedding_provider
from app.rag.evaluation import EvalConfig, run_evaluation
from app.rag.llm import LLMProvider, get_llm_provider
from app.rag.reranker import Reranker

logger = logging.getLogger(__name__)

MAX_VARIANTS = 8
CHUNK_STRATEGIES = ("fixed_size", "recursive", "sentence")
TEMP_PREFIX = "__exp__"
MAX_VARIANT_DOCS = 15
MAX_VARIANT_CHARS = 600_000
EMBED_BATCH = 64
COMPARE_KEYS = ("hit@5", "recall@5", "precision@5", "mrr", "ndcg@5", "faithfulness", "correctness")


# ------------------------------------------------------------------ variants

def validate_variants(variants: Any) -> List[dict]:
    """Normalized variants (each with a unique label); raises ValueError."""
    if not isinstance(variants, list) or not variants:
        raise ValueError("an experiment needs at least one variant")
    if len(variants) > MAX_VARIANTS:
        raise ValueError(f"at most {MAX_VARIANTS} variants per experiment")

    normalized: List[dict] = []
    labels = set()
    for position, raw in enumerate(variants, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"variant {position} must be an object")
        config = EvalConfig.from_dict(raw)
        variant: Dict[str, Any] = config.to_dict()

        chunking = raw.get("chunking")
        if chunking:
            if not isinstance(chunking, dict):
                raise ValueError(f"variant {position}: chunking must be an object")
            strategy = str(chunking.get("strategy", "")).strip().lower()
            if strategy not in CHUNK_STRATEGIES:
                raise ValueError(f"variant {position}: chunking strategy must be one of {', '.join(CHUNK_STRATEGIES)}")
            try:
                size, overlap = int(chunking.get("chunk_size")), int(chunking.get("overlap", 0))
            except (TypeError, ValueError):
                raise ValueError(f"variant {position}: chunk_size and overlap must be numbers")
            if not 100 <= size <= 4000:
                raise ValueError(f"variant {position}: chunk_size must be between 100 and 4000")
            if not 0 <= overlap <= size // 2:
                raise ValueError(f"variant {position}: overlap must be between 0 and half the chunk size")
            variant["chunking"] = {"strategy": strategy, "chunk_size": size, "overlap": overlap}

        label = " ".join(str(raw.get("label") or "").split()) or config.describe()
        if chunking:
            label = label if raw.get("label") else f"{label} | {strategy} {size}/{overlap}"
        if label in labels:
            raise ValueError(f"duplicate variant label: {label!r}")
        labels.add(label)
        variant["label"] = label[:120]
        normalized.append(variant)
    return normalized


# ----------------------------------------------------------------- bootstrap

def paired_bootstrap(diffs: List[float], resamples: int = 2000, seed: int = 0, alpha: float = 0.05) -> Optional[dict]:
    """
    Mean of the per-question differences with a bootstrap confidence interval.
    `significant` means the interval excludes zero. None when there are fewer than 2 pairs.
    """
    n = len(diffs)
    if n < 2:
        return None
    rng = random.Random(seed)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    low = means[int((alpha / 2) * resamples)]
    high = means[int((1 - alpha / 2) * resamples) - 1]
    return {"mean": sum(diffs) / n, "ci_low": low, "ci_high": high, "n": n, "significant": low > 0 or high < 0}


def question_values(details: dict) -> Dict[str, float]:
    """Flat per-question numbers from a stored result (retrieval metrics + generation grades)."""
    values: Dict[str, float] = dict(details.get("metrics") or {})
    generation = details.get("generation") or {}
    for key in ("faithfulness", "correctness"):
        if generation.get(key) is not None:
            values[key] = generation[key]
    return values


# --------------------------------------------------- temporary chunking copy

def _delete_workspace(db: Session, workspace_id: int) -> None:
    doc_ids = [row[0] for row in db.query(Document.id).filter(Document.workspace_id == workspace_id).all()]
    if doc_ids:
        db.query(Chunk).filter(Chunk.document_id.in_(doc_ids)).delete(synchronize_session=False)
        db.query(Document).filter(Document.id.in_(doc_ids)).delete(synchronize_session=False)
    db.query(Workspace).filter(Workspace.id == workspace_id).delete(synchronize_session=False)
    db.commit()


def purge_temporary_workspaces(db: Session) -> int:
    """Removes temporary workspaces left behind by a crashed run."""
    stale = db.query(Workspace.id).filter(Workspace.name.startswith(TEMP_PREFIX, autoescape=True)).all()
    for (workspace_id,) in stale:
        _delete_workspace(db, workspace_id)
    return len(stale)


@contextmanager
def chunking_variant_workspace(db: Session, source_workspace_id: int, chunking: dict):
    """
    Yields the id of a temporary workspace holding the source workspace's documents
    re-chunked with `chunking`. The workspace is always deleted afterwards.
    """
    documents = (
        db.query(Document)
        .filter(
            Document.workspace_id == source_workspace_id,
            Document.deleted_at.is_(None),
            Document.status == "processed",
            Document.raw_text.isnot(None),
        )
        .order_by(Document.id)
        .all()
    )
    if not documents:
        raise ValueError("The workspace has no processed documents with stored text to re-chunk")
    if len(documents) > MAX_VARIANT_DOCS:
        raise ValueError(f"Chunking variants support at most {MAX_VARIANT_DOCS} documents")
    if sum(len(d.raw_text) for d in documents) > MAX_VARIANT_CHARS:
        raise ValueError(f"Chunking variants support at most {MAX_VARIANT_CHARS} characters of document text")

    purge_temporary_workspaces(db)
    workspace = Workspace(name=f"{TEMP_PREFIX}{uuid.uuid4().hex[:12]}")
    db.add(workspace)
    db.commit()
    workspace_id = workspace.id

    try:
        embedder = get_embedding_provider()
        for source in documents:
            pieces = chunk_text(
                source.raw_text, strategy=chunking["strategy"],
                chunk_size=chunking["chunk_size"], overlap=chunking["overlap"],
            )
            if not pieces:
                continue
            copy = Document(
                filename=source.filename, status="processed", source_type=source.source_type,
                workspace_id=workspace_id,
            )
            db.add(copy)
            db.flush()
            vectors: List[list] = []
            for start in range(0, len(pieces), EMBED_BATCH):
                vectors.extend(embedder.embed_batch(pieces[start:start + EMBED_BATCH]))
            for index, (piece, vector) in enumerate(zip(pieces, vectors)):
                db.add(Chunk(
                    document_id=copy.id, content=piece, embedding=vector, chunk_index=index,
                    strategy=chunking["strategy"], chunk_size=chunking["chunk_size"], overlap=chunking["overlap"],
                ))
        db.commit()
        yield workspace_id
    finally:
        db.rollback()
        _delete_workspace(db, workspace_id)


# --------------------------------------------------------------------- runs

def run_variant(
    db: Session,
    experiment: Experiment,
    index: int,
    llm: Optional[LLMProvider] = None,
    reranker: Optional[Reranker] = None,
) -> EvalRun:
    if not 0 <= index < len(experiment.variants):
        raise ValueError("variant index out of range")
    variant = experiment.variants[index]
    eval_set = db.get(EvalSet, experiment.eval_set_id)
    config = EvalConfig.from_dict(variant)

    needs_llm = config.generate or bool(config.transforms)
    active_llm = llm if llm is not None else (get_llm_provider() if needs_llm else None)

    common = dict(
        llm=active_llm, reranker=reranker, label=variant["label"],
        experiment_id=experiment.id, variant_index=index,
    )
    if variant.get("chunking"):
        with chunking_variant_workspace(db, eval_set.workspace_id, variant["chunking"]) as temp_workspace:
            return run_evaluation(db, eval_set, config, workspace_id=temp_workspace, **common)
    return run_evaluation(db, eval_set, config, **common)


def build_comparison(db: Session, experiment: Experiment) -> dict:
    """Latest completed run of each variant, compared with variant 0 question by question."""
    runs = (
        db.query(EvalRun)
        .filter(EvalRun.experiment_id == experiment.id, EvalRun.status == "completed")
        .order_by(EvalRun.id)
        .all()
    )
    latest: Dict[int, EvalRun] = {}
    for run in runs:
        if run.variant_index is not None:
            latest[run.variant_index] = run           # later runs overwrite earlier ones

    def values_by_question(run: EvalRun) -> Dict[int, Dict[str, float]]:
        results = db.query(EvalResult).filter(EvalResult.run_id == run.id).all()
        return {r.question_id: question_values(r.details) for r in results if "error" not in r.details}

    base_values = values_by_question(latest[0]) if 0 in latest else {}
    rows = []
    for index, variant in enumerate(experiment.variants):
        run = latest.get(index)
        row: Dict[str, Any] = {
            "index": index,
            "label": variant["label"],
            "config": variant,
            "run_id": run.id if run else None,
            "metrics": run.metrics if run else None,
            "llm_calls": run.llm_calls if run else 0,
            "elapsed_ms": run.elapsed_ms if run else None,
            "delta_vs_baseline": None,
        }
        if run and index != 0 and base_values:
            other = values_by_question(run)
            deltas: Dict[str, Any] = {}
            for key in COMPARE_KEYS:
                diffs = [
                    other[qid][key] - base_values[qid][key]
                    for qid in other
                    if qid in base_values and key in other[qid] and key in base_values[qid]
                ]
                stats = paired_bootstrap(diffs)
                if stats is not None:
                    deltas[key] = stats
            row["delta_vs_baseline"] = deltas
        rows.append(row)

    return {
        "experiment": {
            "id": experiment.id,
            "name": experiment.name,
            "description": experiment.description,
            "eval_set_id": experiment.eval_set_id,
            "created_at": experiment.created_at.isoformat() if experiment.created_at else None,
        },
        "baseline_index": 0,
        "variants": rows,
    }