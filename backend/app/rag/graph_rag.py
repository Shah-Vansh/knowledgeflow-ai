"""
Graph retrieval and graph-augmented answering (Phase 12).

Flow for a question:
  1. entity linking   - which known entities are named in the question (whole-word match)
  2. traversal        - walk the relationships around them, up to `hops` steps
  3. evidence         - the chunks those relationships were extracted from
  4. fusion           - evidence chunks are fused (RRF) with the normal hybrid/rerank results
  5. answer           - the LLM sees the graph facts AND the text, and may use only those

Everything is scoped to one workspace, in SQL.
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Chunk, ChunkEntity, Document, Entity, Relationship
from app.rag.embeddings import get_embedding_provider
from app.rag.graph_extract import contains_phrase, normalize_text
from app.rag.llm import LLMProvider, get_llm_provider
from app.rag.pipeline import NO_INFO_RESPONSE, retrieve_context
from app.rag.reranker import Reranker
from app.rag.retriever import RRF_K, reciprocal_rank_fusion_many

logger = logging.getLogger(__name__)

MAX_ENTITIES_SCANNED = 5000
MAX_SEED_ENTITIES = 8
MAX_EDGES = 40
MENTION_BONUS = 0.5


@dataclass
class GraphRetrieval:
    seeds: List[Entity] = field(default_factory=list)
    facts: List[dict] = field(default_factory=list)
    chunks: List[Tuple[Chunk, float]] = field(default_factory=list)   # evidence, best first
    hops: int = 0


def find_query_entities(
    db: Session, workspace_id: int, question: str, limit: int = MAX_SEED_ENTITIES
) -> List[Entity]:
    """
    Entities of this workspace whose name appears (whole words) in the question.
    Longer names win: 'AI Text Detector' suppresses a separate 'Text' match.
    """
    normalized_question = normalize_text(question)
    if not normalized_question:
        return []

    candidates = (
        db.query(Entity).filter(Entity.workspace_id == workspace_id).limit(MAX_ENTITIES_SCANNED).all()
    )
    matched = [e for e in candidates if contains_phrase(normalized_question, e.normalized_name)]
    matched.sort(key=lambda e: (-len(e.normalized_name), e.id))

    chosen: List[Entity] = []
    for entity in matched:
        if any(contains_phrase(other.normalized_name, entity.normalized_name) for other in chosen):
            continue                                   # a longer, already-chosen name covers it
        chosen.append(entity)
        if len(chosen) >= limit:
            break
    return chosen


def traverse_graph(
    db: Session,
    workspace_id: int,
    seed_ids: List[int],
    hops: int = 2,
    max_edges: int = MAX_EDGES,
) -> Tuple[List[Tuple[Relationship, int]], Set[int]]:
    """
    Breadth-first walk over relationships, treating edges as undirected for reachability.
    Returns ([(relationship, hop)], visited entity ids). Stops at `hops` steps or max_edges.
    """
    visited: Set[int] = set(seed_ids)
    frontier: Set[int] = set(seed_ids)
    edges: Dict[int, Tuple[Relationship, int]] = {}

    for hop in range(1, hops + 1):
        if not frontier or len(edges) >= max_edges:
            break

        relationships = (
            db.query(Relationship)
            .filter(
                Relationship.workspace_id == workspace_id,
                or_(Relationship.source_id.in_(frontier), Relationship.target_id.in_(frontier)),
            )
            .order_by(Relationship.id)
            .limit(max_edges * 3)
            .all()
        )

        next_frontier: Set[int] = set()
        for relationship in relationships:
            if relationship.id in edges:
                continue
            if len(edges) >= max_edges:
                break
            edges[relationship.id] = (relationship, hop)
            for endpoint in (relationship.source_id, relationship.target_id):
                if endpoint not in visited:
                    visited.add(endpoint)
                    next_frontier.add(endpoint)
        frontier = next_frontier

    return sorted(edges.values(), key=lambda item: (item[1], item[0].id)), visited


def _evidence_chunks(
    db: Session, workspace_id: int, chunk_ids: List[int]
) -> Dict[int, Tuple[Chunk, Document]]:
    if not chunk_ids:
        return {}
    rows = (
        db.query(Chunk, Document)
        .join(Document, Chunk.document_id == Document.id)
        .filter(
            Chunk.id.in_(chunk_ids),
            Document.workspace_id == workspace_id,
            Document.deleted_at.is_(None),
        )
        .all()
    )
    return {chunk.id: (chunk, document) for chunk, document in rows}


def graph_retrieve(
    db: Session,
    question: str,
    workspace_id: int,
    hops: int = 2,
    k: int = 5,
    max_edges: int = MAX_EDGES,
    seeds: Optional[List[Entity]] = None,
) -> GraphRetrieval:
    seeds = seeds if seeds is not None else find_query_entities(db, workspace_id, question)
    if not seeds:
        return GraphRetrieval(hops=hops)

    seed_ids = [e.id for e in seeds]
    edges, visited = traverse_graph(db, workspace_id, seed_ids, hops=hops, max_edges=max_edges)

    names = {
        e.id: e.name
        for e in db.query(Entity).filter(Entity.id.in_(visited)).all()
    }
    evidence = _evidence_chunks(db, workspace_id, list({r.chunk_id for r, _ in edges}))

    facts: List[dict] = []
    scores: Dict[int, float] = {}
    for relationship, hop in edges:
        found = evidence.get(relationship.chunk_id)
        if found is None:
            continue
        chunk, document = found
        facts.append({
            "source": names.get(relationship.source_id, "?"),
            "relation": relationship.relation,
            "target": names.get(relationship.target_id, "?"),
            "chunk_id": chunk.id,
            "document_id": document.id,
            "filename": document.filename,
            "page_number": chunk.page_number,
            "hop": hop,
        })
        scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0

    # chunks that merely mention a seed entity are weaker evidence than relation sources
    mention_rows = (
        db.query(ChunkEntity.chunk_id)
        .filter(ChunkEntity.entity_id.in_(seed_ids))
        .limit(200)
        .all()
    )
    mention_evidence = _evidence_chunks(db, workspace_id, [r[0] for r in mention_rows])
    for chunk_id in mention_evidence:
        scores[chunk_id] = scores.get(chunk_id, 0.0) + MENTION_BONUS
    evidence.update(mention_evidence)

    ranked_ids = sorted(scores, key=lambda cid: (-scores[cid], cid))[:k]
    chunks = [(evidence[cid][0], scores[cid]) for cid in ranked_ids if cid in evidence]

    return GraphRetrieval(seeds=seeds, facts=facts, chunks=chunks, hops=hops)


def format_fact(fact: dict) -> str:
    where = fact["filename"] + (f", page {fact['page_number']}" if fact["page_number"] is not None else "")
    return f"- {fact['source']} -[{fact['relation']}]-> {fact['target']} ({where})"


def answer_with_graph(
    db: Session,
    question: str,
    workspace_id: int,
    k: Optional[int] = None,
    hops: int = 2,
    reranker: Optional[Reranker] = None,
    llm: Optional[LLMProvider] = None,
    seeds: Optional[List[Entity]] = None,
) -> dict:
    """
    Vector + graph retrieval, then one grounded LLM call. The refusal gate is the
    existing one (dense within threshold OR a keyword hit) widened by one more signal:
    the graph found relationships around entities named in the question.
    """
    k = k or settings.TOP_K

    embedder = get_embedding_provider()
    query_vector = embedder.embed(question)

    retrieval = retrieve_context(
        db, question, query_vector, k=k, workspace_id=workspace_id,
        reranker=reranker, transforms=[], llm=llm, embedder=embedder,
    )
    graph = graph_retrieve(db, question, workspace_id, hops=hops, k=k, seeds=seeds)

    graph_info = {
        "matched_entities": [e.name for e in graph.seeds],
        "facts": graph.facts,
        "hops": hops,
        "used": bool(graph.facts),
    }
    mode = "graph+vector" if graph.facts else "vector"

    vector_list = [(item["chunk"], item["score"]) for item in retrieval["ranked"]]
    fused = reciprocal_rank_fusion_many([vector_list, graph.chunks], rrf_k=RRF_K, top_k=k)

    hybrid = retrieval["hybrid"]
    dense_ok = (
        hybrid["best_dense_distance"] is not None
        and hybrid["best_dense_distance"] <= settings.SIMILARITY_THRESHOLD
    )
    sparse_ok = hybrid["sparse_hit_count"] > 0
    graph_ok = bool(graph.facts)

    if not fused or not (dense_ok or sparse_ok or graph_ok):
        return {"answer": NO_INFO_RESPONSE, "sources": [], "graph": graph_info, "mode": mode}

    source_map: Dict[Tuple[int, Optional[int]], dict] = {}
    for chunk, score in fused:
        key = (chunk.document_id, chunk.page_number)
        if key not in source_map:
            source_map[key] = {
                "document_id": chunk.document_id,
                "filename": chunk.document.filename,
                "page_number": chunk.page_number,
                "chunk_ids": [],
                "score": score,
            }
        source_map[key]["chunk_ids"].append(chunk.id)
        source_map[key]["score"] = max(source_map[key]["score"], score)
    sources = sorted(source_map.values(), key=lambda s: s["score"], reverse=True)

    facts_block = ""
    if graph.facts:
        facts_block = (
            "Knowledge graph facts (each was extracted from the text; "
            "entity -[relation]-> entity):\n"
            + "\n".join(format_fact(f) for f in graph.facts)
            + "\n\n"
        )
    passages = "\n\n---\n\n".join(chunk.content for chunk, _ in fused)

    prompt = f"""You are a helpful assistant answering questions using ONLY the knowledge graph facts and text passages below.
If they do not contain enough information to answer the question, respond exactly with:
"{NO_INFO_RESPONSE}"
Do not use any outside knowledge. Do not invent facts, sources, or details that are not present below.

{facts_block}Text passages:
{passages}

Question: {question}

Answer:"""

    answer = (llm or get_llm_provider()).generate(prompt)
    return {"answer": answer, "sources": sources, "graph": graph_info, "mode": mode}