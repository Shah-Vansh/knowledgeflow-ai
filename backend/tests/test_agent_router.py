import json

import pytest

from app.agent.router import RouteDecision, build_router_prompt, decide_route, parse_route
from tests.graph_helpers import FakeLLM


def _json(**fields):
    return json.dumps(fields)


def test_parse_route_each_valid_route():
    assert parse_route(_json(route="rag")).route == "rag"
    assert parse_route(_json(route="graph")).route == "graph"

    calc = parse_route(_json(route="calculator", expression="12 * (3 + 4)"))
    assert (calc.route, calc.expression) == ("calculator", "12 * (3 + 4)")

    search = parse_route(_json(route="document_search", query="budget report"))
    assert (search.route, search.query) == ("document_search", "budget report")

    meta = parse_route(_json(route="metadata", query="count_documents", args={"file_type": "pdf"}))
    assert (meta.route, meta.query, meta.args) == ("metadata", "count_documents", {"file_type": "pdf"})


def test_parse_route_accepts_fences_and_loose_naming():
    decision = parse_route('```json\n{"route": "Document Search", "query": "budget"}\n```')
    assert decision.route == "document_search"
    assert parse_route(_json(route="document-search", query="x")).route == "document_search"


def test_parse_route_ignores_irrelevant_fields():
    decision = parse_route(_json(route="rag", expression="1+1", query="whatever", args={"a": 1}))
    assert decision.expression is None and decision.query is None and decision.args == {}


def test_metadata_args_must_be_an_object():
    decision = parse_route(_json(route="metadata", query="count_chunks", args="pdf"))
    assert decision.args == {}


@pytest.mark.parametrize(
    "raw",
    [
        "I think this should go to rag.",
        "{not json}",
        _json(route="teleport"),
        _json(),
        _json(route="calculator"),
        _json(route="calculator", expression="   "),
        _json(route="calculator", expression="1+" * 150),
        _json(route="document_search"),
        _json(route="metadata"),
        _json(route="metadata", query="drop_table"),
        None,
        42,
    ],
)
def test_parse_route_rejects_unusable_output(raw):
    with pytest.raises(ValueError):
        parse_route(raw)


def test_decide_route_success():
    llm = FakeLLM([_json(route="calculator", expression="2 + 2")])
    decision = decide_route(llm, "What is 2 + 2?")

    assert decision.route == "calculator" and decision.fallback_used is False
    assert llm.temperatures == [0.0]
    assert "What is 2 + 2?" in llm.calls[0]


@pytest.mark.parametrize("script", [[RuntimeError("boom")], ["not json at all"], [_json(route="nope")]])
def test_decide_route_never_raises_and_defaults_to_rag(script):
    decision = decide_route(FakeLLM(script), "anything")

    assert isinstance(decision, RouteDecision)
    assert decision.route == "rag"
    assert decision.fallback_used is True
    assert decision.error


def test_router_prompt_lists_every_route_and_metadata_query():
    prompt = build_router_prompt("hello")
    for name in ("rag", "graph", "document_search", "metadata", "calculator"):
        assert f'"{name}"' in prompt
    for name in ("count_documents", "list_documents", "count_chunks", "document_stats"):
        assert name in prompt