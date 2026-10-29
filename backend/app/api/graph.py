import logging
from collections import Counter
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import DEFAULT_WORKSPACE_ID, get_db, require_workspace
from app.db.models import Chunk, Document, Entity, Relationship
from app.rag.graph_extract import MAX_CHUNKS_PER_BUILD, MAX_GROUP_SIZE, build_document_graph
from app.rag.graph_rag import answer_with_graph
from app.rag.llm import get_llm_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graph", tags=["graph"])

MAX_EDGES_SCANNED = 3000


class BuildRequest(BaseModel):
    max_chunks: int = Field(default=60, ge=1, le=MAX_CHUNKS_PER_BUILD)
    group_size: int = Field(default=4, ge=1, le=MAX_GROUP_SIZE)


class GraphQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    workspace_id: int = DEFAULT_WORKSPACE_ID
    hops: int = Field(default=2, ge=1, le=3)


@router.post("/documents/{document_id}/build")
def build_graph(document_id: int, request: BuildRequest, db: Session = Depends(get_db)):
    """
    Extracts entities and relations from one document's chunks with the LLM and stores
    the validated result. Costs ceil(chunks / group_size) LLM calls (capped), so it only
    runs when asked, never automatically on upload.
    """
    try:
        report = build_document_graph(
            db, document_id, get_llm_provider(),
            max_chunks=request.max_chunks, group_size=request.group_size,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return asdict(report)


@router.get("")
def get_graph(
    workspace_id: int = Query(DEFAULT_WORKSPACE_ID),
    limit: int = Query(60, ge=5, le=200),
    db: Session = Depends(get_db),
):
    """The most connected entities of a workspace and the relationships among them."""
    require_workspace(db, workspace_id)

    relationships = (
        db.query(Relationship)
        .filter(Relationship.workspace_id == workspace_id)
        .order_by(Relationship.id)
        .limit(MAX_EDGES_SCANNED)
        .all()
    )

    degree: Counter = Counter()
    for r in relationships:
        degree[r.source_id] += 1
        degree[r.target_id] += 1

    top_ids = [entity_id for entity_id, _ in degree.most_common(limit)]
    top_set = set(top_ids)
    entities = db.query(Entity).filter(Entity.id.in_(top_ids)).all() if top_ids else []
    edges = [r for r in relationships if r.source_id in top_set and r.target_id in top_set]

    evidence = {}
    chunk_ids = list({r.chunk_id for r in edges})
    if chunk_ids:
        rows = (
            db.query(Chunk, Document)
            .join(Document, Chunk.document_id == Document.id)
            .filter(Chunk.id.in_(chunk_ids), Document.deleted_at.is_(None))
            .all()
        )
        evidence = {chunk.id: (chunk, document) for chunk, document in rows}

    totals = {
        "entities": db.query(func.count(Entity.id)).filter(Entity.workspace_id == workspace_id).scalar(),
        "relationships": db.query(func.count(Relationship.id))
        .filter(Relationship.workspace_id == workspace_id)
        .scalar(),
        "documents_with_graph": db.query(func.count(func.distinct(Relationship.document_id)))
        .filter(Relationship.workspace_id == workspace_id)
        .scalar(),
    }

    return {
        "workspace_id": workspace_id,
        "totals": totals,
        "nodes": [
            {"id": e.id, "name": e.name, "type": e.entity_type, "degree": degree[e.id]}
            for e in sorted(entities, key=lambda e: (-degree[e.id], e.id))
        ],
        "edges": [
            {
                "id": r.id,
                "source": r.source_id,
                "target": r.target_id,
                "relation": r.relation,
                "filename": evidence[r.chunk_id][1].filename if r.chunk_id in evidence else None,
                "page_number": evidence[r.chunk_id][0].page_number if r.chunk_id in evidence else None,
            }
            for r in edges
        ],
    }


@router.post("/query")
def graph_query(request: GraphQueryRequest, db: Session = Depends(get_db)):
    """Vector + graph retrieval for one question, answered from the facts and passages found."""
    require_workspace(db, request.workspace_id)
    try:
        return answer_with_graph(
            db, request.question, request.workspace_id, hops=request.hops, llm=get_llm_provider()
        )
    except Exception:
        logger.exception("Graph query failed")
        db.rollback()
        raise HTTPException(
            status_code=502,
            detail="Answering failed (the language model or search backend returned an error).",
        )