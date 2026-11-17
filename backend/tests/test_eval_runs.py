import json
import re

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.models import EvalQuestion, EvalResult, EvalRun, EvalSet
from app.db.session import SessionLocal
from app.main import app
from app.rag.evaluation import EvalConfig, generate_questions, normalize_for_match, run_evaluation
from app.rag.llm import LLMProvider
from app.rag.reranker import Reranker
from app.rag.pipeline import NO_INFO_RESPONSE
from tests.graph_helpers import (
    FakeLLM,
    NoopReranker,
    cleanup_workspaces,
    ingest_text,
    make_workspace,
)

client = TestClient(app)

CORPUS = {
    "animals.txt": "Capybaras are the largest rodents in the world. Zebras live on the African savanna in herds.",
    "tech.txt": "Postgres supports full text search with tsvector columns. Kubernetes schedules containers across a cluster of nodes.",
    "cooking.txt": "Sourdough bread needs a mature starter and a long fermentation. Risotto is stirred slowly while hot stock is added.",
}

QUESTIONS = [
    ("Which rodent is the largest in the world?", ["largest rodents in the world"], "Capybaras."),
    ("How do zebras live on the savanna?", ["Zebras live on the African savanna"], "In herds on the African savanna."),
    ("What does Kubernetes schedule across a cluster?", ["schedules containers across a cluster of nodes"], "Containers."),
]


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
def world(db_session, workspace_ids):
    """Workspace A holds the corpus; an eval set with the 3 answerable questions lives in it."""
    workspace = make_workspace(db_session, workspace_ids, "eval-a")
    for name, text in CORPUS.items():
        ingest_text(db_session, workspace, name, text)

    created = client.post("/eval/sets", json={"workspace_id": workspace, "name": "golden"})
    assert created.status_code == 201
    set_id = created.json()["id"]
    for question, evidence, reference in QUESTIONS:
        response = client.post(f"/eval/sets/{set_id}/questions", json={
            "question": question, "evidence": evidence, "reference_answer": reference,
        })
        assert response.status_code == 201
    return {"workspace": workspace, "set_id": set_id}


def eval_set(db_session, world) -> EvalSet:
    return db_session.get(EvalSet, world["set_id"])


def add_question(set_id, question, evidence=None, **extra):
    response = client.post(f"/eval/sets/{set_id}/questions", json={"question": question, "evidence": evidence or [], **extra})
    assert response.status_code == 201, response.text
    return response.json()


# ------------------------------------------------------------ retrieval runs

def test_sparse_run_finds_every_target_first(db_session, world):
    run = run_evaluation(db_session, eval_set(db_session, world), EvalConfig.from_dict({"mode": "sparse"}))

    assert run.status == "completed" and run.llm_calls == 0 and run.question_count == 3
    m = run.metrics
    assert (m["n_questions"], m["n_answerable"], m["n_refusal_questions"], m["n_errors"]) == (3, 3, 0, 0)
    assert m["mrr"] == 1.0 and m["hit@1"] == 1.0 and m["recall@5"] == 1.0 and m["ndcg@5"] == 1.0
    assert m["precision@5"] == pytest.approx(0.2)                 # one matching chunk out of five slots
    assert m["retrieval_ms"] > 0


def test_hybrid_run_ranks_the_target_first(db_session, world):
    """The keyword match is in both result lists, so fusion must put it ahead of every dense-only chunk."""
    run = run_evaluation(db_session, eval_set(db_session, world), EvalConfig.from_dict({"mode": "hybrid"}))
    assert run.metrics["mrr"] == 1.0 and run.metrics["hit@1"] == 1.0


def test_hybrid_with_rerank_and_dense_runs(db_session, world):
    reranked = run_evaluation(
        db_session, eval_set(db_session, world), EvalConfig.from_dict({"mode": "hybrid", "rerank": True}),
        reranker=NoopReranker(),
    )
    assert reranked.metrics["mrr"] == 1.0 and reranked.label == "hybrid + rerank"

    dense = run_evaluation(db_session, eval_set(db_session, world), EvalConfig.from_dict({"mode": "dense"}))
    assert dense.metrics["hit@10"] == 1.0 and dense.metrics["recall@10"] == 1.0     # all 6 chunks fit in the top 10
    assert 0.0 <= dense.metrics["mrr"] <= 1.0


def test_run_details_are_stored_and_served(db_session, world):
    created = client.post("/eval/runs", json={"eval_set_id": world["set_id"], "config": {"mode": "sparse"}, "label": "my run"})
    assert created.status_code == 200
    run_id = created.json()["id"]
    assert created.json()["label"] == "my run" and created.json()["config"]["mode"] == "sparse"

    detail = client.get(f"/eval/runs/{run_id}").json()
    assert len(detail["results"]) == 3
    first = detail["results"][0]
    assert first["first_relevant_rank"] == 1 and first["metrics"]["mrr"] == 1.0
    top = first["retrieved"][0]
    assert top["relevant"] is True and top["matched_evidence"] == [0] and top["filename"] == "animals.txt"
    assert "largest rodents" in top["snippet"]

    listed = client.get(f"/eval/runs?eval_set_id={world['set_id']}").json()
    assert [r["id"] for r in listed] == [run_id]
    assert client.get("/eval/runs/999999").status_code == 404


def test_filename_constraint_makes_evidence_in_the_wrong_file_not_count(db_session, world):
    add_question(world["set_id"], "Which animal is the largest rodent of all?", ["largest rodents in the world"], filename="tech.txt")

    run = run_evaluation(db_session, eval_set(db_session, world), EvalConfig.from_dict({"mode": "sparse"}))

    # the three normal questions hit, the fourth finds the right text in the WRONG file
    assert run.metrics["n_answerable"] == 4
    assert run.metrics["hit@5"] == pytest.approx(0.75)
    wrong = [r for r in db_session.query(EvalResult).filter(EvalResult.run_id == run.id) if r.details["question"].startswith("Which animal")][0]
    assert wrong.details["first_relevant_rank"] is None


def test_runs_only_see_their_own_workspace(db_session, workspace_ids, world):
    other = make_workspace(db_session, workspace_ids, "eval-b")
    ingest_text(db_session, other, "animals_copy.txt", CORPUS["animals.txt"])        # same text, other workspace

    run = run_evaluation(db_session, eval_set(db_session, world), EvalConfig.from_dict({"mode": "sparse"}))

    files = {item["filename"] for r in db_session.query(EvalResult).filter(EvalResult.run_id == run.id) for item in r.details["retrieved"]}
    assert "animals_copy.txt" not in files

    empty = make_workspace(db_session, workspace_ids, "eval-empty")
    empty_set = client.post("/eval/sets", json={"workspace_id": empty, "name": "empty corpus"}).json()["id"]
    add_question(empty_set, *QUESTIONS[0][:2])
    empty_run = run_evaluation(db_session, db_session.get(EvalSet, empty_set), EvalConfig.from_dict({"mode": "hybrid"}))
    assert empty_run.status == "completed"
    assert empty_run.metrics["mrr"] == 0.0 and empty_run.metrics["hit@10"] == 0.0


def test_a_failing_question_is_recorded_and_left_out_of_the_averages(db_session, world, monkeypatch):
    import app.rag.evaluation as evaluation

    real = evaluation.retrieve_for_eval

    def flaky(db, question, *args, **kwargs):
        if "zebras" in question:
            raise RuntimeError("search backend hiccup")
        return real(db, question, *args, **kwargs)

    monkeypatch.setattr(evaluation, "retrieve_for_eval", flaky)
    run = run_evaluation(db_session, eval_set(db_session, world), EvalConfig.from_dict({"mode": "sparse"}))

    assert run.status == "completed"
    assert (run.metrics["n_questions"], run.metrics["n_answerable"], run.metrics["n_errors"]) == (3, 2, 1)
    assert run.metrics["mrr"] == 1.0
    failed = [r for r in db_session.query(EvalResult).filter(EvalResult.run_id == run.id) if "error" in r.details]
    assert len(failed) == 1 and "hiccup" in failed[0].details["error"]


def test_a_run_where_everything_fails_is_stored_as_failed(db_session, world, monkeypatch):
    import app.rag.evaluation as evaluation

    def broken(*args, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(evaluation, "retrieve_for_eval", broken)
    run = run_evaluation(db_session, eval_set(db_session, world), EvalConfig.from_dict({"mode": "sparse"}))

    assert run.status == "failed" and run.metrics is None and run.error == "Every question failed"


# ------------------------------------------------------- generation and judge

@pytest.fixture
def lenient_gate(monkeypatch):
    """Dense similarity can never pass, so only keyword hits open the grounding gate (deterministic)."""
    monkeypatch.setattr(settings, "SIMILARITY_THRESHOLD", -1.0)


def judge(faithful, correct):
    return json.dumps({"faithful": faithful, "correct": correct})


def test_generation_run_scores_answers_with_the_judge(db_session, world, lenient_gate):
    add_question(world["set_id"], "What is the capital of Atlantis?", should_refuse=True)
    llm = FakeLLM([
        "Capybaras.", judge("yes", "yes"),
        "Zebras live in herds.", judge("partial", "no"),
        "Kubernetes schedules containers.", judge("yes", "partial"),
    ])

    run = run_evaluation(
        db_session, eval_set(db_session, world),
        EvalConfig.from_dict({"mode": "hybrid", "generate": True}), llm=llm, reranker=NoopReranker(),
    )

    gen = run.metrics["generation"]
    assert gen["faithfulness"] == pytest.approx((1 + 0.5 + 1) / 3)
    assert gen["correctness"] == pytest.approx((1 + 0 + 0.5) / 3)
    assert gen["refusal_accuracy"] == 1.0 and gen["false_refusal_rate"] == 0.0
    assert gen["answers_generated"] == 4 and gen["skipped"] == 0
    assert run.llm_calls == 6 and len(llm.calls) == 6            # the refusal question cost no LLM call at all

    first_judge_prompt = llm.calls[1]
    assert "Capybaras." in first_judge_prompt and "largest rodents" in first_judge_prompt
    assert llm.temperatures[1] == 0.0                            # the judge runs at temperature 0


class CountingReranker(Reranker):
    def __init__(self):
        self.calls = 0

    def score(self, query, passages):
        self.calls += 1
        return [0.0] * len(passages)


def test_answers_are_generated_with_the_variants_own_rerank_setting(db_session, world, lenient_gate, monkeypatch):
    """The global RERANK_ENABLED must not leak into a variant: rerank=False means no reranker call at all."""
    monkeypatch.setattr(settings, "RERANK_ENABLED", True)
    reranker = CountingReranker()
    script = ["Capybaras.", judge("yes", "yes"), "Zebras.", judge("yes", "yes"), "Containers.", judge("yes", "yes")]

    off = run_evaluation(
        db_session, eval_set(db_session, world), EvalConfig.from_dict({"mode": "hybrid", "rerank": False, "generate": True}),
        llm=FakeLLM(list(script)), reranker=reranker,
    )
    assert off.status == "completed" and reranker.calls == 0

    on = run_evaluation(
        db_session, eval_set(db_session, world), EvalConfig.from_dict({"mode": "hybrid", "rerank": True, "generate": True}),
        llm=FakeLLM(list(script)), reranker=reranker,
    )
    assert on.status == "completed" and reranker.calls == 6             # 3 retrievals + 3 answer pipelines


def test_refusals_are_scored_without_the_judge(db_session, world, lenient_gate):
    only = client.post("/eval/sets", json={"workspace_id": world["workspace"], "name": "refusals"}).json()["id"]
    add_question(only, "Which rodent is the largest in the world?", ["largest rodents in the world"])
    add_question(only, "What are capybaras and rodents?", should_refuse=True)          # answerable, so refusing is correct only if it refuses

    llm = FakeLLM([NO_INFO_RESPONSE, "Capybaras are rodents."])
    run = run_evaluation(
        db_session, db_session.get(EvalSet, only), EvalConfig.from_dict({"mode": "hybrid", "generate": True}),
        llm=llm, reranker=NoopReranker(),
    )

    gen = run.metrics["generation"]
    assert gen["false_refusal_rate"] == 1.0                      # it refused a question it could answer
    assert gen["correctness"] == 0.0
    assert gen["refusal_accuracy"] == 0.0                        # and answered a question it was told to refuse
    assert run.llm_calls == 2                                    # no judge calls at all


def test_the_llm_call_budget_skips_the_remaining_questions(db_session, world, lenient_gate):
    llm = FakeLLM(["Capybaras.", judge("yes", "yes")])

    run = run_evaluation(
        db_session, eval_set(db_session, world),
        EvalConfig.from_dict({"mode": "hybrid", "generate": True, "max_llm_calls": 2}), llm=llm, reranker=NoopReranker(),
    )

    gen = run.metrics["generation"]
    assert gen["answers_generated"] == 1 and gen["skipped"] == 2
    assert run.llm_calls == 2
    skipped = [r.details["generation"]["skipped"] for r in db_session.query(EvalResult).filter(EvalResult.run_id == run.id)]
    assert skipped.count("LLM call budget reached") == 2


def test_an_unusable_judge_reply_is_recorded_not_fatal(db_session, world, lenient_gate):
    llm = FakeLLM(["Capybaras.", "I cannot grade this."] + ["answer", judge("yes", "yes")] * 2)

    run = run_evaluation(
        db_session, eval_set(db_session, world), EvalConfig.from_dict({"mode": "hybrid", "generate": True}),
        llm=llm, reranker=NoopReranker(),
    )

    results = db_session.query(EvalResult).filter(EvalResult.run_id == run.id).order_by(EvalResult.id).all()
    assert results[0].details["generation"]["judge_error"] and results[0].details["generation"]["faithfulness"] is None
    assert run.metrics["generation"]["faithfulness"] == 1.0      # averaged over the two graded answers


# --------------------------------------------------- drafting questions

LONG_TEXT = (
    "The Atlas rocket program began in the nineteen fifties and delivered satellites into low earth orbit for many decades, "
    "which made it one of the most reliable launch systems ever operated by the agency. "
    "Sourdough baking depends on a mature starter that is fed regularly with flour and water, because the wild yeast and "
    "bacteria in the culture produce both the rise and the characteristic tangy flavor of the loaf. "
    "Glaciers store most of the fresh water on the planet, and as the climate warms their meltwater raises sea levels, "
    "changes river flows and threatens the supply of drinking water for millions of people downstream."
)


class DraftingLLM(LLMProvider):
    """Writes one valid question per numbered passage, plus one with invented evidence."""

    def __init__(self):
        self.calls = []

    def generate(self, prompt, temperature=0.2):
        self.calls.append(prompt)
        items = []
        for number, text in re.findall(r"^\[(\d+)\] (.*)$", prompt, flags=re.M):
            words = text.split()
            items.append({
                "chunk": int(number),
                "question": f"What is described about {' '.join(words[1:4])}?",
                "evidence": " ".join(words[2:9]),
                "answer": "An answer.",
            })
        items.append({"chunk": 1, "question": "A question with invented evidence?", "evidence": "words that appear nowhere at all", "answer": "x"})
        return json.dumps({"items": items})


def test_drafted_questions_are_verified_against_their_chunks(db_session, workspace_ids):
    workspace = make_workspace(db_session, workspace_ids, "draft")
    ingest_text(db_session, workspace, "long.txt", LONG_TEXT, strategy="sentence", chunk_size=300)
    new_set = client.post("/eval/sets", json={"workspace_id": workspace, "name": "drafts"}).json()["id"]
    llm = DraftingLLM()

    report = generate_questions(db_session, db_session.get(EvalSet, new_set), llm, count=3, seed=1)

    assert (report["sampled"], report["created"], report["rejected"], report["llm_calls"]) == (3, 3, 1, 1)
    questions = db_session.query(EvalQuestion).filter(EvalQuestion.eval_set_id == new_set).all()
    assert len(questions) == 3 and {q.source for q in questions} == {"generated"} and {q.filename for q in questions} == {"long.txt"}
    corpus = f" {normalize_for_match(LONG_TEXT)} "
    assert all(f" {normalize_for_match(q.evidence[0])} " in corpus for q in questions)      # every quote is verbatim

    again = generate_questions(db_session, db_session.get(EvalSet, new_set), DraftingLLM(), count=3, seed=1)
    assert again["created"] == 0                                                            # same questions are not added twice
    assert db_session.query(EvalQuestion).filter(EvalQuestion.eval_set_id == new_set).count() == 3


def test_drafting_survives_a_failing_model_and_a_corpus_that_is_too_short(db_session, workspace_ids, world):
    workspace = make_workspace(db_session, workspace_ids, "draft2")
    ingest_text(db_session, workspace, "long.txt", LONG_TEXT, strategy="sentence", chunk_size=300)
    new_set = client.post("/eval/sets", json={"workspace_id": workspace, "name": "drafts"}).json()["id"]

    report = generate_questions(db_session, db_session.get(EvalSet, new_set), FakeLLM([RuntimeError("down")]), count=3)
    assert report["created"] == 0 and report["failed_calls"] == 1

    # the shared corpus only has chunks shorter than 150 characters
    with pytest.raises(ValueError):
        generate_questions(db_session, eval_set(db_session, world), DraftingLLM(), count=3)


# ---------------------------------------------------------------------- API

def test_set_and_question_crud_and_validation(db_session, world):
    set_id = world["set_id"]
    detail = client.get(f"/eval/sets/{set_id}").json()
    assert [q["question"] for q in detail["questions"]] == [q[0] for q in QUESTIONS]
    assert client.get(f"/eval/sets?workspace_id={world['workspace']}").json()[0]["question_count"] == 3

    url = f"/eval/sets/{set_id}/questions"
    assert client.post(url, json={"question": "Which rodent is the largest in the world?", "evidence": ["largest rodents in the world"]}).status_code == 409
    assert client.post(url, json={"question": "A question without any evidence"}).status_code == 422
    assert client.post(url, json={"question": "A refusal that has evidence", "evidence": ["some specific words"], "should_refuse": True}).status_code == 422
    assert client.post(url, json={"question": "A question with vague evidence", "evidence": ["rodents"]}).status_code == 422
    assert client.post(url, json={"question": "abc", "evidence": ["some specific words"]}).status_code == 422
    assert client.post("/eval/sets/999999/questions", json={"question": "Does this set exist?", "evidence": ["some specific words"]}).status_code == 404
    assert client.post("/eval/sets", json={"workspace_id": 999999, "name": "x"}).status_code == 404

    question_id = detail["questions"][0]["id"]
    assert client.delete(f"/eval/questions/{question_id}").status_code == 200
    assert client.delete(f"/eval/questions/{question_id}").status_code == 404


def test_run_endpoint_validation(db_session, world):
    assert client.post("/eval/runs", json={"eval_set_id": 999999}).status_code == 404
    assert client.post("/eval/runs", json={"eval_set_id": world["set_id"], "config": {"mode": "bm25"}}).status_code == 422
    assert client.post("/eval/runs", json={"eval_set_id": world["set_id"], "config": {"mode": "dense", "rerank": True}}).status_code == 422

    empty = client.post("/eval/sets", json={"workspace_id": world["workspace"], "name": "no questions"}).json()["id"]
    response = client.post("/eval/runs", json={"eval_set_id": empty})
    assert response.status_code == 422 and "no questions" in response.json()["detail"]


def test_deleting_a_set_removes_its_questions_runs_and_results(db_session, world):
    run_id = client.post("/eval/runs", json={"eval_set_id": world["set_id"], "config": {"mode": "sparse"}}).json()["id"]

    assert client.delete(f"/eval/sets/{world['set_id']}").status_code == 200

    db_session.expire_all()
    assert db_session.query(EvalQuestion).filter(EvalQuestion.eval_set_id == world["set_id"]).count() == 0
    assert db_session.get(EvalRun, run_id) is None
    assert db_session.query(EvalResult).filter(EvalResult.run_id == run_id).count() == 0
    assert client.delete(f"/eval/sets/{world['set_id']}").status_code == 404


def test_generation_and_drafting_through_the_api(db_session, world, lenient_gate, monkeypatch):
    monkeypatch.setattr(settings, "RERANK_ENABLED", False)
    llm = FakeLLM(["Capybaras.", judge("yes", "yes"), "Zebras.", judge("yes", "yes"), "Containers.", judge("yes", "yes")])
    monkeypatch.setattr("app.api.evaluation.get_llm_provider", lambda: llm)

    response = client.post("/eval/runs", json={"eval_set_id": world["set_id"], "config": {"mode": "hybrid", "generate": True}})

    assert response.status_code == 200
    assert response.json()["llm_calls"] == 6 and response.json()["metrics"]["generation"]["correctness"] == 1.0

    monkeypatch.setattr("app.api.evaluation.get_llm_provider", lambda: DraftingLLM())
    too_short = client.post(f"/eval/sets/{world['set_id']}/generate", json={"count": 3})
    assert too_short.status_code == 422                           # this corpus has no chunk long enough
    assert client.post(f"/eval/sets/{world['set_id']}/generate", json={"count": 99}).status_code == 422