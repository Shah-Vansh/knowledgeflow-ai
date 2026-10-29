import json

import pytest

from app.rag.graph_extract import (
    MAX_ENTITIES_PER_CALL,
    contains_phrase,
    normalize_entity_name,
    normalize_text,
    parse_extraction,
)

CHUNKS = [
    "RoBERTa is a transformer model that was developed by Meta AI.",
    "Streamlit provides the web interface used to run RoBERTa online.",
    "The AI Text Detector project was built by a team at LJ Institute.",
]


def test_normalization():
    assert normalize_text("The AI-Text  Detector!") == "the ai text detector"
    assert normalize_entity_name("The AI Text Detector!") == "ai text detector"
    assert normalize_entity_name("an Apple") == "apple"
    assert normalize_entity_name("Meta AI") == "meta ai"


def test_contains_phrase_is_whole_word():
    assert contains_phrase("developed by meta ai", "meta ai")
    assert not contains_phrase("metaai is not it", "meta ai")
    assert not contains_phrase("anaconda", "ana")
    assert not contains_phrase("anything", "")


def _parse(entities=None, relations=None):
    return parse_extraction(json.dumps({"entities": entities or [], "relations": relations or []}), CHUNKS)


def test_entities_must_appear_in_the_text():
    result = _parse(entities=[
        {"name": "RoBERTa", "type": "TECH"},
        {"name": "Quantum Banana", "type": "CONCEPT"},
    ])
    assert list(result.entities) == ["roberta"]
    assert result.dropped_entities == 1
    assert result.entities["roberta"].positions == {1, 2}      # mentioned in chunks 1 and 2
    assert result.entities["roberta"].entity_type == "TECH"


def test_entity_types_and_names_are_cleaned():
    result = _parse(entities=[
        {"name": "  Meta AI ", "type": "org"},
        {"name": "Streamlit", "type": "gadget"},
        {"name": "x" * 81, "type": "ORG"},
        {"name": "A", "type": "ORG"},
        {"name": 5, "type": "ORG"},
        "not an object",
    ])
    assert result.entities["meta ai"].entity_type == "ORG"
    assert result.entities["streamlit"].entity_type == "OTHER"
    assert set(result.entities) == {"meta ai", "streamlit"}
    assert result.dropped_entities == 4


def test_relations_must_be_grounded_in_the_cited_chunk():
    result = _parse(relations=[
        {"source": "RoBERTa", "relation": "developed by", "target": "Meta AI", "chunk": 1},          # ok
        {"source": "RoBERTa", "relation": "invented by", "target": "Streamlit", "chunk": 1},         # Streamlit not in chunk 1
        {"source": "RoBERTa", "relation": "uses", "target": "Quantum Banana", "chunk": 1},           # not in text at all
        {"source": "RoBERTa", "relation": "x", "target": "Meta AI", "chunk": 9},                      # no such chunk
        {"source": "RoBERTa", "relation": "x", "target": "Meta AI", "chunk": 0},
        {"source": "RoBERTa", "relation": "x", "target": "Meta AI", "chunk": "one"},
        {"source": "RoBERTa", "relation": "is", "target": "RoBERTa", "chunk": 1},                     # self loop
        {"source": "RoBERTa", "relation": "", "target": "Meta AI", "chunk": 1},                       # no label
        {"source": "RoBERTa", "target": "Meta AI", "chunk": 1},                                       # missing label
        "not an object",
    ])
    assert result.relations == [("roberta", "developed by", "meta ai", 1)]
    assert result.dropped_relations == 9


def test_relation_endpoints_are_added_even_if_not_listed():
    result = _parse(relations=[
        {"source": "Streamlit", "relation": "Provides Interface For!!", "target": "RoBERTa", "chunk": "2"},
    ])
    assert set(result.entities) == {"streamlit", "roberta"}
    assert result.entities["streamlit"].entity_type == "OTHER"
    assert result.relations == [("streamlit", "provides interface for", "roberta", 2)]


def test_duplicate_relations_are_collapsed():
    item = {"source": "RoBERTa", "relation": "developed by", "target": "Meta AI", "chunk": 1}
    result = _parse(relations=[item, dict(item), {**item, "relation": "DEVELOPED BY"}])
    assert len(result.relations) == 1


def test_leading_article_does_not_create_a_second_entity():
    result = _parse(entities=[{"name": "The AI Text Detector"}, {"name": "AI Text Detector"}])
    assert list(result.entities) == ["ai text detector"]


def test_entity_count_is_capped():
    chunk = " ".join(f"alpha{i}" for i in range(60))
    names = [{"name": f"alpha{i}", "type": "OTHER"} for i in range(60)]
    result = parse_extraction(json.dumps({"entities": names, "relations": []}), [chunk])
    assert len(result.entities) == MAX_ENTITIES_PER_CALL


@pytest.mark.parametrize("raw", ["no json here", "[1, 2]", "{bad json}", None, 42])
def test_unparseable_replies_raise(raw):
    with pytest.raises(ValueError):
        parse_extraction(raw, CHUNKS)


def test_wrong_shaped_fields_are_tolerated():
    result = parse_extraction(json.dumps({"entities": "RoBERTa", "relations": {"a": 1}}), CHUNKS)
    assert result.entities == {} and result.relations == []