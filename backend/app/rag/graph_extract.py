"""
Knowledge-graph construction (Phase 12).

An LLM proposes entities and relations for groups of chunks, and then EVERYTHING it
says is checked against the chunk text before it is stored:

  * an entity is kept only if its name appears word-for-word in at least one chunk
  * a relation is kept only if the chunk it cites contains BOTH endpoint names
  * every relation is stored with the single chunk it came from (evidence)

So the graph can contain a wrong relation label, but never an entity or a link with
no supporting text, and deleting a chunk deletes everything derived from it.
"""
import logging
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.db.models import Chunk, ChunkEntity, Document, Entity, Relationship
from app.rag.json_utils import extract_json_object
from app.rag.llm import LLMProvider

logger = logging.getLogger(__name__)

ENTITY_TYPES = ("PERSON", "ORG", "TECH", "CONCEPT", "LOCATION", "PRODUCT", "EVENT", "OTHER")

MAX_ENTITIES_PER_CALL = 30
MAX_RELATIONS_PER_CALL = 30
MAX_NAME_CHARS = 80
MAX_RELATION_CHARS = 40
MAX_CHUNK_CHARS_IN_PROMPT = 1200

MAX_CHUNKS_PER_BUILD = 200
MAX_GROUP_SIZE = 8
MAX_LLM_CALLS_PER_BUILD = 30   # keeps one build inside a free-tier rate limit


# ---------------------------------------------------------------- text helpers

def normalize_text(text: str) -> str:
    """Lowercase, punctuation -> spaces, collapsed whitespace."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text).lower()).split())


def normalize_entity_name(name: str) -> str:
    """normalize_text, minus a leading article ('the AI Text Detector' == 'AI Text Detector')."""
    text = normalize_text(name)
    return re.sub(r"^(the|a|an) ", "", text)


def contains_phrase(normalized_text: str, normalized_phrase: str) -> bool:
    """Whole-word containment on already-normalized strings."""
    return bool(normalized_phrase) and f" {normalized_phrase} " in f" {normalized_text} "


def _clean_name(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    name = " ".join(value.split()).strip("\"'`[]()")
    if len(name) < 2 or len(name) > MAX_NAME_CHARS:
        return None
    return name


def _clean_relation(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    label = " ".join(re.sub(r"[^a-z0-9 '/\-]", " ", value.lower()).split())
    if not label or len(label) > MAX_RELATION_CHARS or not any(ch.isalnum() for ch in label):
        return None
    return label


def _entity_type(value: Any) -> str:
    candidate = str(value or "").strip().upper()
    return candidate if candidate in ENTITY_TYPES else "OTHER"


# ------------------------------------------------------------------ extraction

@dataclass
class ExtractedEntity:
    name: str
    entity_type: str
    positions: Set[int] = field(default_factory=set)   # 1-based chunk positions in the group


@dataclass
class ExtractionResult:
    entities: Dict[str, ExtractedEntity] = field(default_factory=dict)         # normalized name -> entity
    relations: List[Tuple[str, str, str, int]] = field(default_factory=list)   # (src, relation, tgt, position)
    dropped_entities: int = 0
    dropped_relations: int = 0


def build_extraction_prompt(chunk_texts: List[str]) -> str:
    numbered = "\n\n".join(
        f"[{i}] {text[:MAX_CHUNK_CHARS_IN_PROMPT]}" for i, text in enumerate(chunk_texts, start=1)
    )
    types = ", ".join(ENTITY_TYPES)
    return f"""You extract a knowledge graph from numbered text passages.

Rules:
- Reply with ONLY one JSON object. No markdown, no commentary.
- "entities": the important named things (people, organizations, technologies, products, places, concepts). Each item: {{"name": the exact words used in the text, "type": one of {types}}}.
- "relations": facts that connect two entities. Each item: {{"source": entity name, "relation": a short verb phrase of 1 to 4 words such as "developed by", "uses" or "part of", "target": entity name, "chunk": the number N of the passage [N] that states the fact}}.
- Entity names MUST appear word-for-word in the passage the fact comes from. Never invent entities or facts. Never use outside knowledge.
- At most {MAX_ENTITIES_PER_CALL} entities and {MAX_RELATIONS_PER_CALL} relations. If there is nothing useful, return {{"entities": [], "relations": []}}.

Passages:
{numbered}

JSON:"""


def parse_extraction(raw: Any, chunk_texts: List[str]) -> ExtractionResult:
    """
    Validates a model reply against the chunk texts it was asked about. Raises
    ValueError if the reply is not a JSON object; everything else that is wrong with
    individual items is silently dropped (and counted).
    """
    data = extract_json_object(raw)
    normalized_texts = [normalize_text(text) for text in chunk_texts]
    result = ExtractionResult()

    def positions_of(norm_name: str) -> Set[int]:
        return {i for i, t in enumerate(normalized_texts, start=1) if contains_phrase(t, norm_name)}

    def add_entity(name: str, entity_type: str) -> Optional[str]:
        norm = normalize_entity_name(name)
        if len(norm) < 2:
            return None
        found = positions_of(norm)
        if not found:
            return None                      # not in the text: never store it
        existing = result.entities.get(norm)
        if existing is None:
            if len(result.entities) >= MAX_ENTITIES_PER_CALL:
                return None
            existing = ExtractedEntity(name=name, entity_type=entity_type)
            result.entities[norm] = existing
        existing.positions |= found
        return norm

    raw_entities = data.get("entities")
    for item in (raw_entities if isinstance(raw_entities, list) else [])[: MAX_ENTITIES_PER_CALL * 2]:
        name = _clean_name(item.get("name")) if isinstance(item, dict) else None
        if name is None or add_entity(name, _entity_type(item.get("type"))) is None:
            result.dropped_entities += 1

    seen: Set[Tuple[str, str, str, int]] = set()
    raw_relations = data.get("relations")
    for item in (raw_relations if isinstance(raw_relations, list) else [])[: MAX_RELATIONS_PER_CALL * 2]:
        if len(result.relations) >= MAX_RELATIONS_PER_CALL:
            break
        if not isinstance(item, dict):
            result.dropped_relations += 1
            continue

        source_name, target_name = _clean_name(item.get("source")), _clean_name(item.get("target"))
        label = _clean_relation(item.get("relation"))
        try:
            position = int(item.get("chunk"))
        except (TypeError, ValueError):
            position = 0

        if not (source_name and target_name and label) or not 1 <= position <= len(chunk_texts):
            result.dropped_relations += 1
            continue

        source_norm, target_norm = normalize_entity_name(source_name), normalize_entity_name(target_name)
        evidence = normalized_texts[position - 1]
        grounded = (
            source_norm != target_norm
            and contains_phrase(evidence, source_norm)
            and contains_phrase(evidence, target_norm)
        )
        if not grounded:
            result.dropped_relations += 1
            continue

        # both endpoints are present in the cited chunk, so they may be added even if
        # the model forgot to list them under "entities"
        if add_entity(source_name, "OTHER") is None or add_entity(target_name, "OTHER") is None:
            result.dropped_relations += 1
            continue

        key = (source_norm, label, target_norm, position)
        if key in seen:
            continue
        seen.add(key)
        result.relations.append(key)

    return result


# ----------------------------------------------------------------------- build

@dataclass
class BuildReport:
    document_id: int
    chunks_total: int
    chunks_processed: int
    groups_total: int
    groups_failed: int
    llm_calls: int
    entities: int
    mentions: int
    relationships: int
    dropped_entities: int
    dropped_relations: int
    truncated: bool
    elapsed_ms: float


def prune_orphan_entities(db: Session, workspace_id: int) -> int:
    """Deletes entities that no chunk mentions and no relationship uses."""
    from sqlalchemy import select

    pruned = (
        db.query(Entity)
        .filter(
            Entity.workspace_id == workspace_id,
            ~Entity.id.in_(select(ChunkEntity.entity_id)),
            ~Entity.id.in_(select(Relationship.source_id)),
            ~Entity.id.in_(select(Relationship.target_id)),
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return pruned


def build_document_graph(
    db: Session,
    document_id: int,
    llm: LLMProvider,
    max_chunks: int = 60,
    group_size: int = 4,
) -> BuildReport:
    """
    Builds (or rebuilds) the knowledge graph for one document.

    Costs ceil(min(chunks, max_chunks) / group_size) LLM calls, capped at
    MAX_LLM_CALLS_PER_BUILD. A group whose call fails is skipped and counted; if EVERY
    call fails the previous graph is left untouched and RuntimeError is raised.
    Raises LookupError (document missing/deleted) and ValueError (bad parameters,
    no chunks, or too many calls).
    """
    started = time.perf_counter()

    if not 1 <= max_chunks <= MAX_CHUNKS_PER_BUILD:
        raise ValueError(f"max_chunks must be between 1 and {MAX_CHUNKS_PER_BUILD}")
    if not 1 <= group_size <= MAX_GROUP_SIZE:
        raise ValueError(f"group_size must be between 1 and {MAX_GROUP_SIZE}")

    document = db.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise LookupError("Document not found")

    chunks = (
        db.query(Chunk).filter(Chunk.document_id == document_id).order_by(Chunk.chunk_index).all()
    )
    if not chunks:
        raise ValueError("Document has no chunks to build a graph from")

    to_process = chunks[:max_chunks]
    groups = [to_process[i:i + group_size] for i in range(0, len(to_process), group_size)]
    if len(groups) > MAX_LLM_CALLS_PER_BUILD:
        raise ValueError(
            f"This would need {len(groups)} LLM calls (limit {MAX_LLM_CALLS_PER_BUILD}); "
            f"lower max_chunks or raise group_size"
        )

    collected: List[Tuple[List[Chunk], ExtractionResult]] = []
    failed = 0
    for group in groups:
        try:
            raw = llm.generate(build_extraction_prompt([c.content for c in group]), temperature=0.0)
            collected.append((group, parse_extraction(raw, [c.content for c in group])))
        except Exception as exc:
            failed += 1
            logger.warning("Graph extraction failed for a group of %d chunks: %s", len(group), exc)

    if not collected:
        raise RuntimeError("Every extraction call failed; the existing graph was left unchanged")

    workspace_id = document.workspace_id

    # replace this document's previous graph data
    db.query(Relationship).filter(Relationship.document_id == document_id).delete(
        synchronize_session=False
    )
    db.query(ChunkEntity).filter(ChunkEntity.chunk_id.in_([c.id for c in chunks])).delete(
        synchronize_session=False
    )
    db.flush()

    entity_ids: Dict[str, int] = {}

    def entity_id_for(norm: str, extracted: ExtractedEntity) -> int:
        if norm in entity_ids:
            return entity_ids[norm]
        existing = (
            db.query(Entity)
            .filter(Entity.workspace_id == workspace_id, Entity.normalized_name == norm)
            .first()
        )
        if existing is None:
            existing = Entity(
                workspace_id=workspace_id,
                name=extracted.name,
                normalized_name=norm,
                entity_type=extracted.entity_type,
            )
            db.add(existing)
            db.flush()
        entity_ids[norm] = existing.id
        return existing.id

    mention_pairs: Set[Tuple[int, int]] = set()
    relationship_count = dropped_entities = dropped_relations = 0

    for group, result in collected:
        dropped_entities += result.dropped_entities
        dropped_relations += result.dropped_relations

        for norm, extracted in result.entities.items():
            entity_id = entity_id_for(norm, extracted)
            for position in extracted.positions:
                pair = (group[position - 1].id, entity_id)
                if pair not in mention_pairs:
                    mention_pairs.add(pair)
                    db.add(ChunkEntity(chunk_id=pair[0], entity_id=pair[1]))

        for source_norm, label, target_norm, position in result.relations:
            db.add(
                Relationship(
                    workspace_id=workspace_id,
                    document_id=document_id,
                    chunk_id=group[position - 1].id,
                    source_id=entity_ids[source_norm],
                    target_id=entity_ids[target_norm],
                    relation=label,
                )
            )
            relationship_count += 1

    db.commit()
    prune_orphan_entities(db, workspace_id)

    return BuildReport(
        document_id=document_id,
        chunks_total=len(chunks),
        chunks_processed=len(to_process),
        groups_total=len(groups),
        groups_failed=failed,
        llm_calls=len(groups),
        entities=len(entity_ids),
        mentions=len(mention_pairs),
        relationships=relationship_count,
        dropped_entities=dropped_entities,
        dropped_relations=dropped_relations,
        truncated=len(chunks) > len(to_process),
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )