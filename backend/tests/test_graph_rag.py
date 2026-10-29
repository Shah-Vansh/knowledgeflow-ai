import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.models import Chunk, ChunkEntity, Entity, Relationship
from app.db.session import SessionLocal
from app.main import app
from app.rag.graph_extract import build_document_graph, prune_orphan_entities
from app.rag.graph_rag import (
    answer_with_graph,
    find_query_entities,
    graph_retrieve,
    traverse_graph,
)
from app.rag.pipeline import NO_INFO_RESPONSE
from tests.graph_helpers import (
    GRAPH_EXTRACTION,
    GRAPH_TEXT,
    FakeLLM,
    ForbiddenLLM,
    NoopReranker,
    cleanup_workspaces,
    ingest_text,
    make_workspace,
)

client = TestClient(app)


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def workspace_ids():
    ids = []
    yield ids
    cleanup_workspaces(ids)


@pytest.fixture
def built(db_session, workspace_ids):
    """A workspace whose document has been through graph building (3 chunks, 5 entities, 3 relations)."""
    workspace_id = make_workspace(db_session, workspace_ids, "graph")
    document = ingest_text(db_session, workspace_id, "graph_doc.txt", GRAPH_TEXT)
    report = build_document_graph(db_session, document.id, FakeLLM([GRAPH_EXTRACTION]))
    return workspace_id, document, report


def _counts(session, workspace_id):
    return (
        session.query(Entity).filter(Entity.workspace_id == workspace_id).count(),
        session.query(Relationship).filter(Relationship.workspace_id == workspace_id).count(),
    )


# ---------------------------------------------------------------- building

def test_build_stores_only_validated_graph(db_session, built):
    workspace_id, document, report = built

    assert report.chunks_total == report.chunks_processed == 3
    assert (report.groups_total, report.groups_failed, report.llm_calls) == (1, 0, 1)
    assert report.entities == 5                       # "Quantum Banana" was never in the text
    assert report.relationships == 3                  # 3 grounded; 3 invalid ones dropped
    assert report.dropped_entities == 1
    assert report.dropped_relations == 3
    assert report.truncated is False

    names = {e.name for e in db_session.query(Entity).filter(Entity.workspace_id == workspace_id)}
    assert names == {"RoBERTa", "Meta AI", "Streamlit", "AI Text Detector", "LJ Institute"}

    chunks = (
        db_session.query(Chunk).filter(Chunk.document_id == document.id).order_by(Chunk.chunk_index).all()
    )
    assert len(chunks) == 3
    by_entity = {e.id: e.name for e in db_session.query(Entity).filter(Entity.workspace_id == workspace_id)}
    for relationship in db_session.query(Relationship).filter(Relationship.workspace_id == workspace_id):
        evidence = next(c for c in chunks if c.id == relationship.chunk_id)
        # the cited chunk really contains both endpoint names
        assert by_entity[relationship.source_id].lower() in evidence.content.lower()
        assert by_entity[relationship.target_id].lower() in evidence.content.lower()

    mentions = db_session.query(ChunkEntity).filter(ChunkEntity.chunk_id.in_([c.id for c in chunks])).count()
    assert mentions == report.mentions == 6           # RoBERTa is mentioned in two chunks


def test_rebuild_replaces_instead_of_duplicating(db_session, built):
    workspace_id, document, _ = built
    before = _counts(db_session, workspace_id)

    report = build_document_graph(db_session, document.id, FakeLLM([GRAPH_EXTRACTION]))

    assert _counts(db_session, workspace_id) == before == (5, 3)
    assert report.relationships == 3


def test_a_failed_group_is_skipped_and_counted(db_session, workspace_ids):
    workspace_id = make_workspace(db_session, workspace_ids)
    document = ingest_text(db_session, workspace_id, "graph_doc.txt", GRAPH_TEXT)

    llm = FakeLLM([
        json.dumps({"relations": [{"source": "RoBERTa", "relation": "developed by", "target": "Meta AI", "chunk": 1}]}),
        RuntimeError("rate limited"),
        json.dumps({"relations": [{"source": "AI Text Detector", "relation": "built at", "target": "LJ Institute", "chunk": 1}]}),
    ])
    report = build_document_graph(db_session, document.id, llm, group_size=1)

    assert (report.groups_total, report.groups_failed, report.llm_calls) == (3, 1, 3)
    assert report.relationships == 2


def test_when_every_call_fails_the_old_graph_is_kept(db_session, built):
    workspace_id, document, _ = built

    with pytest.raises(RuntimeError):
        build_document_graph(db_session, document.id, FakeLLM([RuntimeError("down")]))

    assert _counts(db_session, workspace_id) == (5, 3)


def test_build_validates_input(db_session, workspace_ids, monkeypatch):
    workspace_id = make_workspace(db_session, workspace_ids)
    document = ingest_text(db_session, workspace_id, "graph_doc.txt", GRAPH_TEXT)

    with pytest.raises(LookupError):
        build_document_graph(db_session, 999999, FakeLLM([]))
    with pytest.raises(ValueError):
        build_document_graph(db_session, document.id, FakeLLM([]), max_chunks=0)
    with pytest.raises(ValueError):
        build_document_graph(db_session, document.id, FakeLLM([]), group_size=0)

    monkeypatch.setattr("app.rag.graph_extract.MAX_LLM_CALLS_PER_BUILD", 2)
    with pytest.raises(ValueError) as error:
        build_document_graph(db_session, document.id, FakeLLM([]), group_size=1)   # 3 calls > 2
    assert "LLM calls" in str(error.value)

    from datetime import datetime, timezone
    document.deleted_at = datetime.now(timezone.utc)
    db_session.commit()
    with pytest.raises(LookupError):
        build_document_graph(db_session, document.id, FakeLLM([]))


def test_max_chunks_truncates_and_reports_it(db_session, workspace_ids):
    workspace_id = make_workspace(db_session, workspace_ids)
    document = ingest_text(db_session, workspace_id, "graph_doc.txt", GRAPH_TEXT)

    report = build_document_graph(db_session, document.id, FakeLLM(['{"entities": [], "relations": []}']), max_chunks=2)

    assert (report.chunks_total, report.chunks_processed, report.truncated) == (3, 2, True)


def test_deleting_chunks_removes_the_graph_built_from_them(db_session, built):
    workspace_id, document, _ = built

    db_session.query(Chunk).filter(Chunk.document_id == document.id).delete(synchronize_session=False)
    db_session.commit()

    assert db_session.query(Relationship).filter(Relationship.workspace_id == workspace_id).count() == 0
    assert prune_orphan_entities(db_session, workspace_id) == 5          # entities nothing refers to are pruned
    assert _counts(db_session, workspace_id) == (0, 0)


# --------------------------------------------------------------- retrieval

def test_entity_linking_matches_whole_names_in_the_question(db_session, built):
    workspace_id, _, _ = built

    found = find_query_entities(db_session, workspace_id, "How is Meta AI related to Streamlit?")
    assert [e.name for e in found] == ["Streamlit", "Meta AI"]            # longer names first

    assert [e.name for e in find_query_entities(db_session, workspace_id, "what about the ai text detector?")] == ["AI Text Detector"]
    assert find_query_entities(db_session, workspace_id, "Tell me about metadata") == []
    assert find_query_entities(db_session, workspace_id, "???") == []


def test_traversal_respects_hop_limit(db_session, built):
    workspace_id, _, _ = built
    meta = find_query_entities(db_session, workspace_id, "Meta AI")[0]

    one_hop, visited_one = traverse_graph(db_session, workspace_id, [meta.id], hops=1)
    two_hops, visited_two = traverse_graph(db_session, workspace_id, [meta.id], hops=2)

    assert [(r.relation, hop) for r, hop in one_hop] == [("developed by", 1)]
    assert len(visited_one) == 2                                          # Meta AI, RoBERTa
    assert [(r.relation, hop) for r, hop in two_hops] == [("developed by", 1), ("provides interface for", 2)]
    assert len(visited_two) == 3                                          # + Streamlit

    capped, _ = traverse_graph(db_session, workspace_id, [meta.id], hops=2, max_edges=1)
    assert len(capped) == 1


def test_graph_retrieve_returns_facts_with_evidence(db_session, built):
    workspace_id, _, _ = built

    graph = graph_retrieve(db_session, "How is Meta AI related to Streamlit?", workspace_id, hops=2, k=5)

    assert {e.name for e in graph.seeds} == {"Meta AI", "Streamlit"}
    triples = {(f["source"], f["relation"], f["target"]) for f in graph.facts}
    assert ("RoBERTa", "developed by", "Meta AI") in triples
    assert ("Streamlit", "provides interface for", "RoBERTa") in triples
    assert all(f["filename"] == "graph_doc.txt" for f in graph.facts)
    evidence_text = " ".join(chunk.content for chunk, _ in graph.chunks)
    assert "developed by Meta AI" in evidence_text and "Streamlit provides" in evidence_text


def test_graph_retrieve_with_no_matching_entity_is_empty(db_session, built):
    workspace_id, _, _ = built
    graph = graph_retrieve(db_session, "What is the weather?", workspace_id)
    assert graph.seeds == [] and graph.facts == [] and graph.chunks == []


# ------------------------------------------------------------- workspaces

def test_graph_is_isolated_between_workspaces(db_session, workspace_ids, built):
    workspace_a, _, _ = built
    workspace_b = make_workspace(db_session, workspace_ids, "other")
    document_b = ingest_text(db_session, workspace_b, "other_doc.txt", "Meta AI also funds a lab called Zebra Labs in Paris.")
    build_document_graph(db_session, document_b.id, FakeLLM([json.dumps({
        "entities": [{"name": "Meta AI", "type": "ORG"}, {"name": "Zebra Labs", "type": "ORG"}],
        "relations": [{"source": "Meta AI", "relation": "funds", "target": "Zebra Labs", "chunk": 1}],
    })]))

    # the same entity name exists independently in both workspaces
    assert db_session.query(Entity).filter(Entity.normalized_name == "meta ai", Entity.workspace_id.in_([workspace_a, workspace_b])).count() == 2

    facts_a = graph_retrieve(db_session, "Tell me about Meta AI", workspace_a).facts
    facts_b = graph_retrieve(db_session, "Tell me about Meta AI", workspace_b).facts
    assert {(f["source"], f["target"]) for f in facts_a} == {("RoBERTa", "Meta AI"), ("Streamlit", "RoBERTa")}
    assert {(f["source"], f["target"]) for f in facts_b} == {("Meta AI", "Zebra Labs")}
    assert all(f["filename"] == "graph_doc.txt" for f in facts_a)
    assert all(f["filename"] == "other_doc.txt" for f in facts_b)

    # an entity that only exists in A cannot be linked from B
    assert find_query_entities(db_session, workspace_b, "What is Streamlit?") == []


def test_traversal_ignores_edges_belonging_to_another_workspace(db_session, workspace_ids, built):
    """
    Entities are per-workspace, so a cross-workspace edge cannot arise from normal use.
    This plants one anyway (corrupt data, or a future bug) to prove the edge query itself
    is workspace-scoped and not only protected by how the data happens to be shaped.
    """
    workspace_a, _, _ = built
    workspace_b = make_workspace(db_session, workspace_ids, "rogue")
    document_b = ingest_text(db_session, workspace_b, "rogue_doc.txt", "Some unrelated sentence about gardening tools.")
    chunk_b = db_session.query(Chunk).filter(Chunk.document_id == document_b.id).first()

    entities = {e.name: e.id for e in db_session.query(Entity).filter(Entity.workspace_id == workspace_a)}
    db_session.add(Relationship(
        workspace_id=workspace_b, document_id=document_b.id, chunk_id=chunk_b.id,
        source_id=entities["Meta AI"], target_id=entities["LJ Institute"], relation="secretly funds",
    ))
    db_session.commit()

    edges, visited = traverse_graph(db_session, workspace_a, [entities["Meta AI"]], hops=2)

    assert "secretly funds" not in {r.relation for r, _ in edges}
    assert entities["LJ Institute"] not in visited


# ----------------------------------------------------------------- answers

def test_answer_with_graph_uses_facts_and_cites_sources(db_session, built):
    workspace_id, _, _ = built
    llm = FakeLLM(["Meta AI developed RoBERTa, which Streamlit serves."])

    result = answer_with_graph(
        db_session, "How is Meta AI related to Streamlit?", workspace_id,
        reranker=NoopReranker(), llm=llm,
    )

    assert result["answer"] == "Meta AI developed RoBERTa, which Streamlit serves."
    assert result["mode"] == "graph+vector"
    assert result["graph"]["used"] is True
    assert set(result["graph"]["matched_entities"]) == {"Meta AI", "Streamlit"}
    assert result["sources"] and all(s["filename"] == "graph_doc.txt" for s in result["sources"])

    prompt = llm.calls[0]
    assert "- RoBERTa -[developed by]-> Meta AI (graph_doc.txt)" in prompt
    assert "- Streamlit -[provides interface for]-> RoBERTa (graph_doc.txt)" in prompt
    assert "Question: How is Meta AI related to Streamlit?" in prompt
    assert len(llm.calls) == 1


def test_graph_evidence_alone_can_pass_the_refusal_gate(db_session, built, monkeypatch):
    workspace_id, _, _ = built
    monkeypatch.setattr(settings, "SIMILARITY_THRESHOLD", -1.0)     # dense can never pass

    # keyword search needs EVERY term in one chunk, which this question can't satisfy,
    # so only the graph signal is left
    llm = FakeLLM(["They are connected through RoBERTa."])
    result = answer_with_graph(
        db_session, "How is Meta AI related to Streamlit?", workspace_id,
        reranker=NoopReranker(), llm=llm,
    )

    assert result["answer"] == "They are connected through RoBERTa."
    assert len(llm.calls) == 1


def test_refuses_without_any_signal_and_without_calling_the_llm(db_session, built, monkeypatch):
    workspace_id, _, _ = built
    monkeypatch.setattr(settings, "SIMILARITY_THRESHOLD", -1.0)

    result = answer_with_graph(
        db_session, "zzzz qqqq", workspace_id, reranker=NoopReranker(), llm=ForbiddenLLM(),
    )

    assert result["answer"] == NO_INFO_RESPONSE
    assert result["sources"] == []
    assert result["graph"]["used"] is False


def test_without_a_graph_it_behaves_like_vector_retrieval(db_session, workspace_ids):
    workspace_id = make_workspace(db_session, workspace_ids)
    ingest_text(db_session, workspace_id, "plain.txt", GRAPH_TEXT)            # no graph built
    llm = FakeLLM(["RoBERTa was developed by Meta AI."])

    result = answer_with_graph(
        db_session, "Who developed RoBERTa?", workspace_id, reranker=NoopReranker(), llm=llm,
    )

    assert result["mode"] == "vector"
    assert result["graph"]["facts"] == []
    assert "Knowledge graph facts" not in llm.calls[0]
    assert result["sources"]


# --------------------------------------------------------------------- API

def test_graph_api_build_view_and_query(db_session, workspace_ids, monkeypatch):
    monkeypatch.setattr(settings, "RERANK_ENABLED", False)
    workspace_id = make_workspace(db_session, workspace_ids)
    document = ingest_text(db_session, workspace_id, "graph_doc.txt", GRAPH_TEXT)

    llm = FakeLLM([GRAPH_EXTRACTION, "Meta AI developed RoBERTa."])
    monkeypatch.setattr("app.api.graph.get_llm_provider", lambda: llm)

    built = client.post(f"/graph/documents/{document.id}/build", json={})
    assert built.status_code == 200
    body = built.json()
    assert (body["entities"], body["relationships"], body["llm_calls"]) == (5, 3, 1)

    view = client.get(f"/graph?workspace_id={workspace_id}")
    assert view.status_code == 200
    graph = view.json()
    assert graph["totals"] == {"entities": 5, "relationships": 3, "documents_with_graph": 1}
    degrees = {n["name"]: n["degree"] for n in graph["nodes"]}
    assert degrees["RoBERTa"] == 2 and degrees["Streamlit"] == 1
    assert len(graph["edges"]) == 3
    assert {e["filename"] for e in graph["edges"]} == {"graph_doc.txt"}
    assert graph["nodes"][0]["name"] == "RoBERTa"                          # most connected first

    answered = client.post("/graph/query", json={"question": "How is Meta AI related to Streamlit?", "workspace_id": workspace_id})
    assert answered.status_code == 200
    assert answered.json()["answer"] == "Meta AI developed RoBERTa."
    assert answered.json()["graph"]["used"] is True


def test_graph_api_errors(db_session, workspace_ids, monkeypatch):
    workspace_id = make_workspace(db_session, workspace_ids)
    document = ingest_text(db_session, workspace_id, "graph_doc.txt", GRAPH_TEXT)

    monkeypatch.setattr("app.api.graph.get_llm_provider", lambda: FakeLLM([RuntimeError("down")]))
    assert client.post(f"/graph/documents/{document.id}/build", json={}).status_code == 502
    assert client.post("/graph/documents/999999/build", json={}).status_code == 404
    assert client.post(f"/graph/documents/{document.id}/build", json={"max_chunks": 0}).status_code == 422
    assert client.post(f"/graph/documents/{document.id}/build", json={"group_size": 99}).status_code == 422

    assert client.get("/graph?workspace_id=999999").status_code == 404
    assert client.post("/graph/query", json={"question": "x", "workspace_id": 999999}).status_code == 404
    assert client.post("/graph/query", json={"question": "", "workspace_id": workspace_id}).status_code == 422
    assert client.post("/graph/query", json={"question": "x", "workspace_id": workspace_id, "hops": 9}).status_code == 422