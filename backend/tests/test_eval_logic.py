import json
import math

import pytest

from app.rag.evaluation import (
    EvalConfig,
    aggregate_metrics,
    build_judge_prompt,
    clean_evidence,
    match_evidence,
    normalize_for_match,
    parse_generated,
    parse_judge,
    retrieval_metrics,
)
from app.rag.experiments import MAX_VARIANTS, paired_bootstrap, question_values, validate_variants


# ------------------------------------------------------------------ evidence

def test_clean_evidence_accepts_and_dedupes():
    cleaned = clean_evidence(["  Capybaras are   the largest rodents ", "capybaras ARE the largest rodents!", "", "second snippet here"])
    assert cleaned == ["Capybaras are the largest rodents", "second snippet here"]


@pytest.mark.parametrize(
    "snippets",
    ["not a list", [5], ["x" * 401], ["one"], ["ab cd"], ["a b"], ["s1 words", "s2 words", "s3 words", "s4 words", "s5 words", "s6 words"]],
)
def test_clean_evidence_rejects(snippets):
    with pytest.raises(ValueError):
        clean_evidence(snippets)


def test_match_evidence_is_whole_word_case_and_punctuation_insensitive():
    evidence = [normalize_for_match("largest rodents in the world"), normalize_for_match("zebras live here")]

    assert match_evidence("The LARGEST rodents, in the world!", "a.txt", evidence) == {0}
    assert match_evidence("zebras live here and largest rodents in the world", "a.txt", evidence) == {0, 1}
    assert match_evidence("the largest rodentsin the world", "a.txt", evidence) == set()      # not whole words
    assert match_evidence("unrelated text", "a.txt", evidence) == set()


def test_match_evidence_does_not_match_inside_longer_words():
    evidence = [normalize_for_match("ran fast")]
    assert match_evidence("A veteran fastest of them all", "a.txt", evidence) == set()      # "ran fast" is inside "veteran fastest"
    assert match_evidence("She ran fast, then rested.", "a.txt", evidence) == {0}


def test_match_evidence_filename_constraint():
    evidence = [normalize_for_match("quarterly revenue grew")]
    assert match_evidence("Quarterly revenue grew", "Report.TXT", evidence, "report.txt") == {0}
    assert match_evidence("Quarterly revenue grew", "other.txt", evidence, "report.txt") == set()
    assert match_evidence("Quarterly revenue grew", "other.txt", evidence, None) == {0}


# ------------------------------------------------------------------ metrics

def test_metrics_relevant_chunk_at_rank_two():
    m = retrieval_metrics([set(), {0}, set()], evidence_count=1)

    assert m["mrr"] == 0.5
    assert (m["hit@1"], m["hit@3"], m["hit@5"], m["hit@10"]) == (0.0, 1.0, 1.0, 1.0)
    assert m["recall@1"] == 0.0 and m["recall@3"] == 1.0
    assert m["precision@3"] == pytest.approx(1 / 3) and m["precision@1"] == 0.0
    assert m["ndcg@1"] == 0.0
    assert m["ndcg@3"] == pytest.approx((1 / math.log2(3)) / 1.0)


def test_metrics_two_evidence_snippets():
    m = retrieval_metrics([{0}, {1}, set(), set(), set()], evidence_count=2)

    assert m["recall@1"] == 0.5 and m["recall@3"] == 1.0
    assert m["ndcg@3"] == pytest.approx(1.0)                  # both relevant chunks are ranked first
    assert m["precision@5"] == pytest.approx(0.4)
    assert m["mrr"] == 1.0


def test_metrics_nothing_relevant_and_nothing_retrieved():
    for matches in ([set(), set(), set()], []):
        m = retrieval_metrics(matches, evidence_count=1)
        assert all(value == 0.0 for value in m.values())


def test_metrics_ndcg_is_capped_when_duplicates_are_relevant():
    m = retrieval_metrics([{0}, {0}, {0}], evidence_count=1)
    assert m["ndcg@3"] == 1.0 and m["precision@3"] == 1.0 and m["recall@3"] == 1.0


def test_metrics_precision_uses_k_even_with_fewer_results():
    m = retrieval_metrics([{0}], evidence_count=1)
    assert m["precision@5"] == pytest.approx(0.2) and m["hit@10"] == 1.0


def test_metrics_late_hit():
    m = retrieval_metrics([set()] * 6 + [{0}], evidence_count=1)
    assert m["hit@5"] == 0.0 and m["hit@10"] == 1.0 and m["mrr"] == pytest.approx(1 / 7)


def test_aggregate_metrics_means_and_skips_none():
    means = aggregate_metrics([{"a": 1.0, "b": 0.0}, {"a": 0.0, "b": None}, {"a": 0.5}])
    assert means == {"a": pytest.approx(0.5), "b": 0.0}
    assert aggregate_metrics([]) == {}


# ------------------------------------------------------------------- judge

def test_parse_judge_maps_labels():
    assert parse_judge('{"faithful": "yes", "correct": "partial"}') == {"faithfulness": 1.0, "correctness": 0.5}
    assert parse_judge('```json\n{"faithful": "No"}\n```') == {"faithfulness": 0.0, "correctness": None}
    assert parse_judge('{"faithful": "maybe", "correct": "yes"}') == {"faithfulness": None, "correctness": 1.0}


@pytest.mark.parametrize("raw", ["no json", '{"faithful": "maybe"}', "{}", None])
def test_parse_judge_rejects_unusable_output(raw):
    with pytest.raises(ValueError):
        parse_judge(raw)


def test_judge_prompt_mentions_the_reference_only_when_there_is_one():
    with_reference = build_judge_prompt("Q?", "the reference", ["ctx one"], "an answer")
    assert "the reference" in with_reference and '"correct"' in with_reference and "ctx one" in with_reference

    without = build_judge_prompt("Q?", None, [], "an answer")
    assert "Reference answer" not in without and '"correct"' not in without and "(none)" in without


# ------------------------------------------------------------------- config

def test_config_defaults_roundtrip_and_description():
    config = EvalConfig.from_dict({})
    assert config.to_dict() == {"mode": "hybrid", "rerank": False, "transforms": [], "k": 5, "generate": False, "max_llm_calls": 60}
    assert config.describe() == "hybrid"

    full = EvalConfig.from_dict({"mode": "HYBRID", "rerank": True, "transforms": ["rewrite", "hyde", "rewrite"], "generate": True})
    assert full.transforms == ["rewrite", "hyde"]
    assert full.describe() == "hybrid + rerank + rewrite + hyde + answers"
    assert EvalConfig.from_dict(full.to_dict()) == full


@pytest.mark.parametrize(
    "data",
    [
        "x", {"mode": "bm25"}, {"transforms": ["bogus"]}, {"transforms": "rewrite"}, {"k": 0}, {"k": 11},
        {"k": "five"}, {"max_llm_calls": 0}, {"mode": "dense", "rerank": True}, {"mode": "sparse", "transforms": ["rewrite"]},
        {"mode": "dense", "generate": True},
    ],
)
def test_config_rejects_invalid_input(data):
    with pytest.raises(ValueError):
        EvalConfig.from_dict(data)


# ------------------------------------------------------- generated questions

PASSAGES = ["Capybaras are the largest rodents in the world and live near water.", "Postgres supports full text search with tsvector columns."]


def _generated(*items):
    return json.dumps({"items": list(items)})


def test_parse_generated_keeps_only_verifiable_items():
    raw = _generated(
        {"chunk": 1, "question": "Which rodent is the largest in the world?", "evidence": "largest rodents in the world", "answer": "Capybaras."},
        {"chunk": 2, "question": "Which database feature supports searching text?", "evidence": "invented words that are absent", "answer": "x"},
        {"chunk": 2, "question": "According to the passage, what does Postgres support?", "evidence": "full text search with tsvector", "answer": "x"},
        {"chunk": 9, "question": "Which chunk does not exist at all?", "evidence": "largest rodents in the world", "answer": "x"},
    )
    seen = set()
    valid, rejected = parse_generated(raw, PASSAGES, seen)

    assert [(v["chunk"], v["question"], v["evidence"]) for v in valid] == [
        (1, "Which rodent is the largest in the world?", "largest rodents in the world")
    ]
    assert rejected == 3                      # evidence not in the passage / refers to "the passage" / no such chunk
    assert normalize_for_match("Which rodent is the largest in the world?") in seen


def test_parse_generated_rejects_malformed_short_and_duplicate_items():
    seen = {normalize_for_match("Which rodent is the largest in the world?")}
    raw = _generated(
        {"chunk": 1, "question": "short?", "evidence": "largest rodents in the world", "answer": "x"},
        {"chunk": 1, "question": "Which rodent is the largest in the world?", "evidence": "largest rodents in the world", "answer": "dup"},
        {"chunk": "two", "evidence": "x"},
        "not an object",
    )
    assert parse_generated(raw, PASSAGES, seen) == ([], 4)


def test_parse_generated_examines_at_most_two_items_per_passage():
    items = [
        {"chunk": 1, "question": f"Which rodent number {n} is the largest in the world?", "evidence": "largest rodents in the world", "answer": ""}
        for n in range(10)
    ]
    valid, rejected = parse_generated(_generated(*items), PASSAGES, set())
    assert len(valid) == 4 and rejected == 0                  # 2 passages -> only the first 4 items are looked at


def test_parse_generated_rejects_existing_questions_and_bad_output():
    existing = {normalize_for_match("Which rodent is the largest in the world?")}
    raw = _generated({"chunk": 1, "question": "Which rodent is the largest in the world?", "evidence": "largest rodents in the world", "answer": ""})
    assert parse_generated(raw, PASSAGES, existing) == ([], 1)

    for bad in ("no json", "{}", '{"items": "x"}'):
        with pytest.raises(ValueError):
            parse_generated(bad, PASSAGES, set())


# --------------------------------------------------------- bootstrap / variants

def test_bootstrap_needs_two_pairs_and_is_deterministic():
    assert paired_bootstrap([]) is None and paired_bootstrap([0.5]) is None
    assert paired_bootstrap([0.1, -0.2, 0.3, 0.0], seed=7) == paired_bootstrap([0.1, -0.2, 0.3, 0.0], seed=7)


def test_bootstrap_detects_a_consistent_improvement():
    result = paired_bootstrap([0.5] * 18 + [0.0] * 2)
    assert result["mean"] == pytest.approx(0.45) and result["n"] == 20
    assert result["ci_low"] > 0 and result["significant"] is True


def test_bootstrap_does_not_call_noise_significant():
    result = paired_bootstrap([1.0, -1.0, 1.0, -1.0, 0.0, 0.0])
    assert result["mean"] == 0.0 and result["ci_low"] < 0 < result["ci_high"] and result["significant"] is False


def test_bootstrap_identical_runs_are_not_significant():
    result = paired_bootstrap([0.0] * 5)
    assert result == {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0, "n": 5, "significant": False}


def test_question_values_merges_generation_grades():
    details = {"metrics": {"mrr": 1.0}, "generation": {"faithfulness": 0.5, "correctness": None}}
    assert question_values(details) == {"mrr": 1.0, "faithfulness": 0.5}
    assert question_values({"error": "boom"}) == {}


def test_validate_variants_normalizes_and_labels():
    variants = validate_variants([
        {"mode": "sparse"},
        {"mode": "hybrid", "rerank": True},
        {"mode": "hybrid", "chunking": {"strategy": "sentence", "chunk_size": 500, "overlap": 50}},
        {"label": "my label", "mode": "dense"},
    ])
    assert [v["label"] for v in variants] == ["sparse", "hybrid + rerank", "hybrid | sentence 500/50", "my label"]
    assert variants[2]["chunking"] == {"strategy": "sentence", "chunk_size": 500, "overlap": 50}
    assert "chunking" not in variants[0]


@pytest.mark.parametrize(
    "variants",
    [
        [], "x", [5], [{"mode": "bm25"}], [{"mode": "sparse"}, {"mode": "sparse"}],
        [{"mode": "hybrid", "chunking": "x"}],
        [{"mode": "hybrid", "chunking": {"strategy": "paragraph", "chunk_size": 500}}],
        [{"mode": "hybrid", "chunking": {"strategy": "fixed_size", "chunk_size": 50}}],
        [{"mode": "hybrid", "chunking": {"strategy": "fixed_size", "chunk_size": 500, "overlap": 400}}],
        [{"mode": "hybrid", "chunking": {"strategy": "fixed_size", "chunk_size": "big"}}],
        [{"label": f"v{i}", "mode": "sparse"} for i in range(MAX_VARIANTS + 1)],
    ],
)
def test_validate_variants_rejects(variants):
    with pytest.raises(ValueError):
        validate_variants(variants)