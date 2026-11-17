import pytest
from fastapi.testclient import TestClient

from app.db.models import Chunk, Document, EvalResult, EvalRun, EvalSet, Experiment, Workspace
from app.db.session import SessionLocal
from app.main import app
from app.rag import experiments as experiments_module
from app.rag.chunker import chunk_text
from app.rag.experiments import (
    TEMP_PREFIX,
    chunking_variant_workspace,
    purge_temporary_workspaces,
    run_variant,
)
from tests.graph_helpers import cleanup_workspaces, ingest_text, make_workspace

client = TestClient(app)

CORPUS = {
    "animals.txt": "Capybaras are the largest rodents in the world. Zebras live on the African savanna in herds.",
    "tech.txt": "Postgres supports full text search with tsvector columns. Kubernetes schedules containers across a cluster of nodes.",
    "cooking.txt": "Sourdough bread needs a mature starter and a long fermentation. Risotto is stirred slowly while hot stock is added.",
}

QUESTIONS = [
    ("Which rodent is the largest in the world?", ["largest rodents in the world"]),
    ("How do zebras live on the savanna?", ["Zebras live on the African savanna"]),
    ("What does Kubernetes schedule across a cluster?", ["schedules containers across a cluster of nodes"]),
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
    session = SessionLocal()                     # a failed test must never leave a temporary workspace behind
    try:
        purge_temporary_workspaces(session)
    finally:
        session.close()


def make_set(workspace, questions, name="golden"):
    set_id = client.post("/eval/sets", json={"workspace_id": workspace, "name": name}).json()["id"]
    for text, evidence in questions:
        response = client.post(f"/eval/sets/{set_id}/questions", json={"question": text, "evidence": evidence})
        assert response.status_code == 201, response.text
    return set_id


@pytest.fixture
def world(db_session, workspace_ids):
    workspace = make_workspace(db_session, workspace_ids, "exp")
    for name, text in CORPUS.items():
        ingest_text(db_session, workspace, name, text)
    return {"workspace": workspace, "set_id": make_set(workspace, QUESTIONS)}


def create_experiment(set_id, variants, name="ablation"):
    return client.post("/experiments", json={"eval_set_id": set_id, "name": name, "variants": variants})


def temp_workspaces(session):
    return session.query(Workspace).filter(Workspace.name.startswith(TEMP_PREFIX, autoescape=True)).count()


# ------------------------------------------------------------- comparison

def test_variants_are_run_and_compared_with_the_first_one(db_session, world):
    created = create_experiment(world["set_id"], [{"mode": "sparse"}, {"mode": "dense"}, {"mode": "hybrid"}])
    assert created.status_code == 201
    experiment_id = created.json()["experiment"]["id"]
    assert [v["label"] for v in created.json()["variants"]] == ["sparse", "dense", "hybrid"]
    assert all(v["run_id"] is None and v["metrics"] is None for v in created.json()["variants"])      # nothing run yet

    runs = [client.post(f"/experiments/{experiment_id}/run-variant", json={"index": i}) for i in range(3)]
    assert [r.status_code for r in runs] == [200, 200, 200]
    assert [r.json()["variant_index"] for r in runs] == [0, 1, 2] and all(r.json()["experiment_id"] == experiment_id for r in runs)

    comparison = client.get(f"/experiments/{experiment_id}").json()
    sparse, dense, hybrid = comparison["variants"]
    assert sparse["delta_vs_baseline"] is None and comparison["baseline_index"] == 0
    assert sparse["metrics"]["mrr"] == 1.0 and hybrid["metrics"]["mrr"] == 1.0

    assert hybrid["delta_vs_baseline"]["mrr"]["mean"] == 0.0 and hybrid["delta_vs_baseline"]["mrr"]["significant"] is False
    expected = dense["metrics"]["mrr"] - sparse["metrics"]["mrr"]
    assert dense["delta_vs_baseline"]["mrr"]["mean"] == pytest.approx(expected)
    assert dense["delta_vs_baseline"]["mrr"]["n"] == 3
    assert {"hit@5", "recall@5", "precision@5", "mrr", "ndcg@5"} <= set(dense["delta_vs_baseline"])


def test_the_latest_run_of_a_variant_is_the_one_compared(db_session, world):
    experiment_id = create_experiment(world["set_id"], [{"mode": "sparse"}, {"mode": "hybrid"}]).json()["experiment"]["id"]
    first = client.post(f"/experiments/{experiment_id}/run-variant", json={"index": 1}).json()["id"]
    client.post(f"/experiments/{experiment_id}/run-variant", json={"index": 0})
    second = client.post(f"/experiments/{experiment_id}/run-variant", json={"index": 1}).json()["id"]

    rows = client.get(f"/experiments/{experiment_id}").json()["variants"]

    assert second > first and rows[1]["run_id"] == second
    assert db_session.query(EvalRun).filter(EvalRun.experiment_id == experiment_id).count() == 3      # history is kept


def test_experiment_endpoints_validate_input(db_session, world):
    set_id = world["set_id"]
    assert create_experiment(999999, [{"mode": "sparse"}]).status_code == 404
    assert create_experiment(set_id, []).status_code == 422
    assert create_experiment(set_id, [{"mode": "bm25"}]).status_code == 422
    assert create_experiment(set_id, [{"mode": "sparse"}, {"mode": "sparse"}]).status_code == 422
    assert create_experiment(set_id, [{"label": f"v{i}", "mode": "sparse"} for i in range(9)]).status_code == 422

    experiment_id = create_experiment(set_id, [{"mode": "sparse"}]).json()["experiment"]["id"]
    assert client.post(f"/experiments/{experiment_id}/run-variant", json={"index": 5}).status_code == 422
    assert client.post(f"/experiments/{experiment_id}/run-variant", json={"index": -1}).status_code == 422
    assert client.post("/experiments/999999/run-variant", json={"index": 0}).status_code == 404
    assert client.get("/experiments/999999").status_code == 404
    assert [e["id"] for e in client.get("/experiments").json()][0] == experiment_id


def test_deleting_an_experiment_deletes_its_runs_but_not_the_set(db_session, world):
    experiment_id = create_experiment(world["set_id"], [{"mode": "sparse"}]).json()["experiment"]["id"]
    run_id = client.post(f"/experiments/{experiment_id}/run-variant", json={"index": 0}).json()["id"]

    assert client.delete(f"/experiments/{experiment_id}").status_code == 200

    db_session.expire_all()
    assert db_session.get(Experiment, experiment_id) is None and db_session.get(EvalRun, run_id) is None
    assert db_session.query(EvalResult).filter(EvalResult.run_id == run_id).count() == 0
    assert db_session.get(EvalSet, world["set_id"]) is not None
    assert client.delete(f"/experiments/{experiment_id}").status_code == 404


# ------------------------------------------------------ chunking variants

REPORT_TEXT = (
    "The quarterly report covers revenue growth across every region. Sales in the north grew faster than expected "
    "because two large customers renewed early. Costs stayed flat while the support team doubled in size. "
    "Management expects the trend to continue through the next two quarters unless exchange rates move sharply."
)


def boundary_phrases(text, size):
    """Phrases that straddle each chunk boundary of fixed_size chunking: no single chunk can contain them."""
    pieces = chunk_text(text, "fixed_size", size, 0)
    assert len(pieces) >= 3
    return [" ".join(pieces[i].split()[-3:] + pieces[i + 1].split()[:3]) for i in range(2)]


@pytest.fixture
def chunking_world(db_session, workspace_ids):
    workspace = make_workspace(db_session, workspace_ids, "chunking")
    ingest_text(db_session, workspace, "report.txt", REPORT_TEXT, strategy="sentence", chunk_size=1000)   # one big chunk
    phrases = boundary_phrases(REPORT_TEXT, 100)
    questions = [
        ("What does the quarterly report say about revenue growth?", [phrases[0]]),
        ("How did sales and customers develop in the north?", [phrases[1]]),
    ]
    set_id = make_set(workspace, questions, name="chunking")
    for _, evidence in questions:
        assert evidence[0] in REPORT_TEXT                      # the evidence really is contiguous text of the document
    return {"workspace": workspace, "set_id": set_id}


def counts(session, workspace_id):
    documents = session.query(Document).filter(Document.workspace_id == workspace_id).count()
    chunks = session.query(Chunk).join(Document, Chunk.document_id == Document.id).filter(Document.workspace_id == workspace_id).count()
    return documents, chunks


def test_a_chunking_variant_scores_the_effect_of_splitting_the_evidence(db_session, chunking_world):
    before = counts(db_session, chunking_world["workspace"])
    created = create_experiment(chunking_world["set_id"], [
        {"label": "one big chunk", "mode": "hybrid"},
        {"label": "100-char chunks", "mode": "hybrid", "chunking": {"strategy": "fixed_size", "chunk_size": 100, "overlap": 0}},
    ])
    assert created.status_code == 201
    experiment_id = created.json()["experiment"]["id"]

    for index in (0, 1):
        assert client.post(f"/experiments/{experiment_id}/run-variant", json={"index": index}).status_code == 200

    rows = client.get(f"/experiments/{experiment_id}").json()["variants"]
    assert rows[0]["metrics"]["hit@5"] == 1.0 and rows[0]["metrics"]["recall@5"] == 1.0       # the phrase fits in one chunk
    assert rows[1]["metrics"]["hit@5"] == 0.0 and rows[1]["metrics"]["recall@5"] == 0.0       # every chunk boundary cuts it
    assert rows[1]["delta_vs_baseline"]["hit@5"]["mean"] == -1.0
    assert rows[1]["delta_vs_baseline"]["hit@5"]["significant"] is True

    assert temp_workspaces(db_session) == 0                    # the temporary copy is gone
    assert counts(db_session, chunking_world["workspace"]) == before          # and the real data was never touched
    assert db_session.query(Document).filter(Document.filename == "report.txt").count() == 1


def test_a_failing_run_still_removes_the_temporary_workspace(db_session, chunking_world, monkeypatch):
    experiment = Experiment(
        eval_set_id=chunking_world["set_id"], name="x",
        variants=[{"label": "v", "mode": "hybrid", "rerank": False, "transforms": [], "k": 5, "generate": False,
                   "max_llm_calls": 60, "chunking": {"strategy": "fixed_size", "chunk_size": 100, "overlap": 0}}],
    )
    db_session.add(experiment)
    db_session.commit()

    def boom(*args, **kwargs):
        raise RuntimeError("evaluation crashed")

    monkeypatch.setattr(experiments_module, "run_evaluation", boom)
    with pytest.raises(RuntimeError):
        run_variant(db_session, experiment, 0)

    assert temp_workspaces(db_session) == 0


def test_stale_temporary_workspaces_are_purged(db_session, workspace_ids):
    stale = Workspace(name=f"{TEMP_PREFIX}leftover")
    db_session.add(stale)
    db_session.commit()
    document = Document(filename="old.txt", status="processed", workspace_id=stale.id)
    db_session.add(document)
    db_session.commit()

    assert purge_temporary_workspaces(db_session) == 1
    assert temp_workspaces(db_session) == 0
    assert db_session.query(Document).filter(Document.filename == "old.txt").count() == 0


def test_starting_a_chunking_variant_cleans_up_a_crashed_runs_leftovers(db_session, world):
    stale = Workspace(name=f"{TEMP_PREFIX}crashed")
    db_session.add(stale)
    db_session.commit()
    db_session.add(Document(filename="leftover.txt", status="processed", workspace_id=stale.id))
    db_session.commit()

    with chunking_variant_workspace(db_session, world["workspace"], {"strategy": "sentence", "chunk_size": 500, "overlap": 0}) as temp:
        names = [w.name for w in db_session.query(Workspace).filter(Workspace.name.startswith(TEMP_PREFIX, autoescape=True))]
        assert names and f"{TEMP_PREFIX}crashed" not in names           # only the live temporary workspace exists
        assert db_session.query(Document).filter(Document.workspace_id == temp).count() == 3

    assert temp_workspaces(db_session) == 0
    assert db_session.query(Document).filter(Document.filename == "leftover.txt").count() == 0


def test_chunking_variants_need_documents_with_stored_text(db_session, workspace_ids):
    workspace = make_workspace(db_session, workspace_ids, "nodocs")
    set_id = make_set(workspace, QUESTIONS[:1])
    experiment_id = create_experiment(set_id, [
        {"mode": "hybrid", "chunking": {"strategy": "sentence", "chunk_size": 500, "overlap": 0}},
    ]).json()["experiment"]["id"]

    response = client.post(f"/experiments/{experiment_id}/run-variant", json={"index": 0})

    assert response.status_code == 422 and "no processed documents" in response.json()["detail"]
    assert temp_workspaces(db_session) == 0


def test_chunking_variants_have_size_limits(db_session, world, monkeypatch):
    monkeypatch.setattr(experiments_module, "MAX_VARIANT_DOCS", 2)
    with pytest.raises(ValueError):
        with chunking_variant_workspace(db_session, world["workspace"], {"strategy": "sentence", "chunk_size": 500, "overlap": 0}):
            pass                                              # 3 documents > 2

    monkeypatch.setattr(experiments_module, "MAX_VARIANT_DOCS", 15)
    monkeypatch.setattr(experiments_module, "MAX_VARIANT_CHARS", 10)
    with pytest.raises(ValueError):
        with chunking_variant_workspace(db_session, world["workspace"], {"strategy": "sentence", "chunk_size": 500, "overlap": 0}):
            pass
    assert temp_workspaces(db_session) == 0