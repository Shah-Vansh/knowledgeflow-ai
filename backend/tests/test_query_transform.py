import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.models import Chunk
from app.db.session import SessionLocal
from app.main import app
from app.rag.embeddings import get_embedding_provider
from app.rag.llm import LLMProvider
from app.rag.pipeline import NO_INFO_RESPONSE, answer_question, retrieve_context
from app.rag.pipeline import ingest_document
from app.rag.query_transform import (
    TransformResult,
    normalize_transforms,
    plan_search_jobs,
    transform_query,
)
from app.rag.reranker import Reranker
from app.rag.retriever import (
    reciprocal_rank_fusion,
    reciprocal_rank_fusion_many,
    retrieve_bm25,
    retrieve_bm25_any_term,
)

client = TestClient(app)


class FakeLLM(LLMProvider):
    """Plays back a script: each call returns the next string, or raises the next Exception."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def generate(self, prompt, temperature=0.2):
        self.calls.append(prompt)
        if not self.script:
            raise AssertionError("unexpected extra LLM call")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class NoopReranker(Reranker):
    def score(self, query, passages):
        return [0.0] * len(passages)


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def seeded_document(db_session, tmp_path):
    file_path = tmp_path / "transform_sample.txt"
    file_path.write_text(
        "The company's refund policy allows returns within 30 days. "
        "Our headquarters is located in Berlin, Germany. "
        "The product warranty lasts for two full years after purchase."
    )
    # sentence strategy + small chunk_size => one chunk per sentence (3 chunks)
    document = ingest_document(
        db_session, str(file_path), "transform_sample.txt",
        strategy="sentence", chunk_size=80, overlap=0,
    )
    yield document

    db_session.query(Chunk).filter(Chunk.document_id == document.id).delete()
    db_session.delete(document)
    db_session.commit()


# ---------- strategy name validation ----------

def test_normalize_orders_and_dedupes():
    assert normalize_transforms(["hyde", "rewrite", "hyde"]) == ["rewrite", "hyde"]
    assert normalize_transforms([]) == []
    assert normalize_transforms(None) == []


def test_normalize_rejects_unknown():
    with pytest.raises(ValueError) as error:
        normalize_transforms(["rewrite", "bogus"])
    assert "bogus" in str(error.value)
    assert "Allowed" in str(error.value)


# ---------- parsing the LLM output ----------

def test_transform_parses_valid_json():
    llm = FakeLLM([json.dumps({
        "rewrite": "company refund policy returns window",
        "hyde": "The refund policy allows returns within 30 days.",
    })])
    result = transform_query(llm, "What is the refund policy?", ["rewrite", "hyde"])

    assert result.fallback_used is False
    assert result.rewrite == "company refund policy returns window"
    assert result.hyde == "The refund policy allows returns within 30 days."
    assert len(llm.calls) == 1  # ONE call for all strategies
    assert "What is the refund policy?" in llm.calls[0]
    assert '"keywords"' not in llm.calls[0]  # unrequested keys are not asked for


def test_transform_accepts_fenced_json():
    llm = FakeLLM(['```json\n{"rewrite": "refund policy"}\n```'])
    result = transform_query(llm, "refunds?", ["rewrite"])
    assert result.rewrite == "refund policy"
    assert result.fallback_used is False


def test_transform_invalid_json_falls_back():
    llm = FakeLLM(["Sorry, I cannot do that."])
    result = transform_query(llm, "What is the refund policy?", ["rewrite", "hyde"])
    assert result.fallback_used is True
    assert result.rewrite is None and result.hyde is None
    assert result.error


def test_transform_llm_error_falls_back():
    llm = FakeLLM([RuntimeError("boom")])
    result = transform_query(llm, "What is the refund policy?", ["expand"])
    assert result.fallback_used is True
    assert result.keywords == []
    assert "boom" in result.error


def test_transform_ignores_unrequested_fields():
    llm = FakeLLM([json.dumps({
        "rewrite": "refund policy",
        "hyde": "should be ignored",
        "keywords": ["ignored"],
        "variants": ["ignored too"],
    })])
    result = transform_query(llm, "What is the refund policy?", ["rewrite"])
    assert result.rewrite == "refund policy"
    assert result.hyde is None
    assert result.keywords == []
    assert result.variants == []


def test_transform_cleans_variants():
    llm = FakeLLM([json.dumps({"variants": [
        "How do refunds work?",            # same as the original -> dropped
        "",                                # empty -> dropped
        "  how do refunds   work  ",       # same as the original (normalized) -> dropped
        "What is the refund process?",
        "What is the refund process?",     # duplicate -> dropped
        "Can I get my money back?",
        "Extra one?",
        "One more?",                       # beyond the cap -> dropped
    ]})])
    result = transform_query(llm, "How do refunds work?", ["multi_query"], variant_count=3)
    assert result.variants == [
        "What is the refund process?",
        "Can I get my money back?",
        "Extra one?",
    ]


def test_transform_cleans_keywords():
    llm = FakeLLM([json.dumps({"keywords": ['"machine learning"', "-model", "", "AI", "ai", "!!!"]})])
    result = transform_query(llm, "q", ["expand"])
    assert result.keywords == ["machine learning", "model", "AI"]


# ---------- planning searches ----------

def test_plan_jobs_shapes_and_order():
    result = TransformResult(
        original="What is the refund policy?",
        requested=["rewrite", "expand", "multi_query", "hyde"],
        rewrite="refund policy details",
        keywords=["refund", "return window"],
        variants=["How do refunds work?", "Can I return a product?"],
        hyde="Refunds are accepted within 30 days.",
    )
    jobs = plan_search_jobs(result)

    assert [j.label for j in jobs] == [
        "original", "rewrite", "variant 1", "variant 2", "hyde", "expand",
    ]
    by_label = {j.label: j for j in jobs}
    assert by_label["original"].dense and by_label["original"].sparse
    assert by_label["rewrite"].dense and by_label["rewrite"].sparse
    assert by_label["hyde"].dense and not by_label["hyde"].sparse
    assert by_label["expand"].sparse and not by_label["expand"].dense
    assert by_label["expand"].terms == ["refund", "return window"]


def test_plan_skips_rewrite_identical_to_original():
    result = TransformResult(
        original="What is the refund policy?",
        requested=["rewrite", "multi_query"],
        rewrite="what is the refund policy",
        variants=["WHAT IS THE REFUND POLICY?"],
    )
    assert [j.label for j in plan_search_jobs(result)] == ["original"]


# ---------- retrieval building blocks ----------

def test_any_term_matches_where_and_does_not(seeded_document, db_session):
    ids = [seeded_document.id]

    # AND semantics: no single chunk contains both words
    assert retrieve_bm25(db_session, "refund Berlin", k=5, document_ids=ids) == []

    # OR semantics: each word matches its own chunk
    or_results = retrieve_bm25_any_term(db_session, ["refund", "Berlin"], k=5, document_ids=ids)
    contents = " ".join(chunk.content for chunk, _ in or_results)
    assert len(or_results) == 2
    assert "refund" in contents and "Berlin" in contents

    # nothing usable -> no results, no error
    assert retrieve_bm25_any_term(db_session, [], k=5, document_ids=ids) == []
    assert retrieve_bm25_any_term(db_session, ["!!!", "   "], k=5, document_ids=ids) == []


def test_rrf_many_boosts_chunks_found_by_several_lists():
    a, b, c = (SimpleNamespace(id=i) for i in (1, 2, 3))
    lists = [
        [(a, 0), (b, 0)],
        [(c, 0), (a, 0)],
        [(a, 0), (c, 0)],
    ]
    fused = reciprocal_rank_fusion_many(lists, rrf_k=60, top_k=3)
    assert [chunk.id for chunk, _ in fused] == [1, 3, 2]  # a (3 lists) > c (2) > b (1)

    # the Phase 5 two-list API still works
    two = reciprocal_rank_fusion([(a, 0), (b, 0)], [(a, 0)], rrf_k=60, top_k=2)
    assert two[0][0].id == 1


# ---------- pipeline integration ----------

def _retrieve_with_expand(db_session, document, keywords):
    llm = FakeLLM([json.dumps({"keywords": keywords})])
    embedder = get_embedding_provider()
    question = "zzzz qqqq"  # nonsense: the original query matches nothing by keyword
    return retrieve_context(
        db_session, question, embedder.embed(question), k=3,
        document_ids=[document.id], use_rerank=False,
        transforms=["expand"], llm=llm, embedder=embedder,
    )


def test_retrieve_context_expand_surfaces_chunk_original_missed(seeded_document, db_session):
    retrieval = _retrieve_with_expand(db_session, seeded_document, ["Berlin"])

    assert [job.label for job in retrieval["jobs"]] == ["original", "expand"]

    top_chunk = retrieval["hybrid"]["fused"][0][0]
    assert "Berlin" in top_chunk.content  # keyword match + dense agreement lifts it to #1
    assert retrieval["ranked"][0]["chunk"].id == top_chunk.id

    entry = retrieval["provenance"][top_chunk.id]
    assert entry["expand"] == ["sparse"]
    assert entry["original"] == ["dense"]  # the original never matched it by keyword


def test_grounding_signals_come_from_original_query_only(seeded_document, db_session):
    retrieval = _retrieve_with_expand(db_session, seeded_document, ["Berlin"])

    # the expansion matched a chunk by keyword, but the ORIGINAL query matched nothing
    assert retrieval["hybrid"]["sparse_hit_count"] == 0
    assert retrieval["hybrid"]["best_dense_distance"] is not None


def test_answer_refuses_when_only_expansion_matches(seeded_document, monkeypatch):
    # Make dense unable to pass the gate, so only the keyword signal could.
    monkeypatch.setattr(settings, "SIMILARITY_THRESHOLD", -1.0)
    llm = FakeLLM([json.dumps({"keywords": ["Berlin"]})])  # a 2nd call would raise

    db = SessionLocal()
    try:
        result = answer_question(
            db, "zzzz qqqq", document_ids=[seeded_document.id],
            transforms=["expand"], reranker=NoopReranker(), llm=llm,
        )
    finally:
        db.close()

    assert result["answer"] == NO_INFO_RESPONSE
    assert result["sources"] == []
    assert len(llm.calls) == 1  # only the transformation call; no answer generation


def test_answer_fails_open_when_transform_errors(seeded_document):
    llm = FakeLLM([RuntimeError("boom"), "The refund window is 30 days."])

    db = SessionLocal()
    try:
        result = answer_question(
            db, "What is the refund policy?", document_ids=[seeded_document.id],
            transforms=["rewrite"], reranker=NoopReranker(), llm=llm,
        )
    finally:
        db.close()

    assert result["answer"] == "The refund window is 30 days."
    assert result["transformation_fallback"] is True
    assert result["transforms_used"] == ["rewrite"]
    assert len(result["sources"]) >= 1


# ---------- API ----------

def test_debug_endpoint_returns_transformation_and_provenance(seeded_document, monkeypatch):
    llm = FakeLLM([json.dumps({"keywords": ["Berlin"]})])
    monkeypatch.setattr("app.rag.pipeline.get_llm_provider", lambda: llm)

    response = client.post(
        "/query/retrieve",
        json={
            "question": "zzzz qqqq",
            "k": 3,
            "mode": "hybrid",
            "rerank": False,
            "transforms": ["expand"],
            "document_ids": [seeded_document.id],
        },
    )
    assert response.status_code == 200
    body = response.json()

    assert body["transformation"]["keywords"] == ["Berlin"]
    assert body["transformation"]["fallback_used"] is False
    assert [j["label"] for j in body["transformation"]["jobs"]] == ["original", "expand"]

    top = body["results"][0]
    assert "Berlin" in top["content"]
    assert "sparse" in top["found_by"]
    assert any(q.startswith("expand: sparse") for q in top["found_by_queries"])


def test_unknown_transform_rejected_with_400():
    debug = client.post("/query/retrieve", json={"question": "x", "transforms": ["bogus"]})
    assert debug.status_code == 400
    assert "Allowed" in debug.json()["detail"]

    query = client.post("/query", json={"question": "x", "transforms": ["bogus"]})
    assert query.status_code == 400