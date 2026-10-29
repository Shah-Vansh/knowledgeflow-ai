"""
The agent as a LangGraph state machine (Phase 11).

        START -> route_question --+--> run_rag ------------------------------> END
                                  +--> run_graph --------+
                                  +--> run_document_search +--(tool failed)--> run_rag --> END
                                  +--> run_metadata ------+--(ok)------------> END
                                  +--> run_calculator ----+

Only the router decides with an LLM. Calculator, metadata and document search build
their answers deterministically from the tool result (no second LLM call), and any
tool that cannot handle its input hands the question to the normal RAG pipeline.
"""
import operator
import time
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.agent.router import decide_route
from app.agent.tools import (
    CalculatorError,
    MetadataQueryError,
    format_document_search_answer,
    format_metadata_answer,
    format_number,
    run_metadata_query,
    safe_eval,
    search_documents,
)
from app.rag.graph_rag import answer_with_graph, find_query_entities
from app.rag.llm import LLMProvider
from app.rag.pipeline import answer_question
from app.rag.reranker import Reranker


class CountingLLM(LLMProvider):
    """Wraps a provider and counts calls, so every response can report its LLM cost."""

    def __init__(self, inner: LLMProvider):
        self.inner = inner
        self.calls = 0

    def generate(self, prompt: str, temperature: float = 0.2) -> str:
        self.calls += 1
        return self.inner.generate(prompt, temperature=temperature)


class AgentState(TypedDict, total=False):
    question: str
    route: str                      # what the router chose
    route_args: Dict[str, Any]
    route_expression: Optional[str]
    route_query: Optional[str]
    route_fallback: bool            # router failed/invalid -> defaulted to rag
    route_error: Optional[str]
    used_route: str                 # what actually produced the answer
    tool_failed: bool               # a tool could not handle the question -> rag answers
    fallback_reason: Optional[str]
    answer: str
    sources: List[dict]
    tool_result: Optional[dict]
    graph: Optional[dict]
    trace: Annotated[List[dict], operator.add]


def _step(name: str, started: float, detail: str) -> List[dict]:
    return [{"step": name, "detail": detail, "ms": round((time.perf_counter() - started) * 1000, 1)}]


def run_agent(
    db: Session,
    question: str,
    workspace_id: int,
    llm: LLMProvider,
    reranker: Optional[Reranker] = None,
) -> dict:
    counting = CountingLLM(llm)

    def route_question(state: AgentState) -> dict:
        started = time.perf_counter()
        decision = decide_route(counting, state["question"])
        detail = f"chose '{decision.route}'" + (
            f" (router unusable, defaulted to rag: {decision.error})" if decision.fallback_used else ""
        )
        return {
            "route": decision.route,
            "route_args": decision.args,
            "route_expression": decision.expression,
            "route_query": decision.query,
            "route_fallback": decision.fallback_used,
            "route_error": decision.error,
            "trace": _step("route", started, detail),
        }

    def run_rag(state: AgentState) -> dict:
        started = time.perf_counter()
        result = answer_question(
            db, state["question"], workspace_id=workspace_id, reranker=reranker, llm=counting,
            transforms=[],
        )
        return {
            "answer": result["answer"],
            "sources": result["sources"],
            "used_route": "rag",
            "trace": _step("rag", started, f"hybrid retrieval, {len(result['sources'])} source(s)"),
        }

    def run_graph(state: AgentState) -> dict:
        started = time.perf_counter()
        seeds = find_query_entities(db, workspace_id, state["question"])
        if not seeds:
            return {
                "tool_failed": True,
                "fallback_reason": "no known graph entities are named in the question",
                "trace": _step("graph", started, "no entities matched; handing over to rag"),
            }
        result = answer_with_graph(
            db, state["question"], workspace_id, reranker=reranker, llm=counting, seeds=seeds
        )
        return {
            "answer": result["answer"],
            "sources": result["sources"],
            "graph": result["graph"],
            "used_route": "graph",
            "trace": _step(
                "graph", started,
                f"{len(seeds)} entit{'y' if len(seeds) == 1 else 'ies'} matched, "
                f"{len(result['graph']['facts'])} fact(s)",
            ),
        }

    def run_document_search(state: AgentState) -> dict:
        started = time.perf_counter()
        try:
            result = search_documents(db, workspace_id, state.get("route_query") or "")
        except MetadataQueryError as exc:
            return {
                "tool_failed": True,
                "fallback_reason": str(exc),
                "trace": _step("document_search", started, f"failed: {exc}"),
            }
        return {
            "answer": format_document_search_answer(result),
            "sources": [],
            "tool_result": result,
            "used_route": "document_search",
            "trace": _step("document_search", started, f"{len(result['documents'])} match(es)"),
        }

    def run_metadata(state: AgentState) -> dict:
        started = time.perf_counter()
        try:
            result = run_metadata_query(
                db, workspace_id, state.get("route_query") or "", state.get("route_args")
            )
        except MetadataQueryError as exc:
            return {
                "tool_failed": True,
                "fallback_reason": str(exc),
                "trace": _step("metadata", started, f"failed: {exc}"),
            }
        return {
            "answer": format_metadata_answer(result),
            "sources": [],
            "tool_result": result,
            "used_route": "metadata",
            "trace": _step("metadata", started, result["query"]),
        }

    def run_calculator(state: AgentState) -> dict:
        started = time.perf_counter()
        expression = state.get("route_expression") or ""
        try:
            value = safe_eval(expression)
        except CalculatorError as exc:
            return {
                "tool_failed": True,
                "fallback_reason": f"calculator could not evaluate the expression: {exc}",
                "trace": _step("calculator", started, f"failed: {exc}"),
            }
        shown = format_number(value)
        return {
            "answer": f"{expression} = {shown}",
            "sources": [],
            "tool_result": {"expression": expression, "result": value},
            "used_route": "calculator",
            "trace": _step("calculator", started, f"{expression} = {shown}"),
        }

    def after_tool(state: AgentState) -> str:
        return "run_rag" if state.get("tool_failed") else "done"

    graph = StateGraph(AgentState)
    graph.add_node("route_question", route_question)
    graph.add_node("run_rag", run_rag)
    graph.add_node("run_graph", run_graph)
    graph.add_node("run_document_search", run_document_search)
    graph.add_node("run_metadata", run_metadata)
    graph.add_node("run_calculator", run_calculator)

    graph.add_edge(START, "route_question")
    graph.add_conditional_edges(
        "route_question",
        lambda state: state["route"],
        {
            "rag": "run_rag",
            "graph": "run_graph",
            "document_search": "run_document_search",
            "metadata": "run_metadata",
            "calculator": "run_calculator",
        },
    )
    for tool in ("run_graph", "run_document_search", "run_metadata", "run_calculator"):
        graph.add_conditional_edges(tool, after_tool, {"run_rag": "run_rag", "done": END})
    graph.add_edge("run_rag", END)

    final = graph.compile().invoke({"question": question, "trace": []})

    return {
        "answer": final.get("answer", ""),
        "route": final.get("route", "rag"),
        "used_route": final.get("used_route", "rag"),
        "route_fallback": bool(final.get("route_fallback")),
        "fallback_to_rag": bool(final.get("tool_failed")),
        "fallback_reason": final.get("fallback_reason"),
        "sources": final.get("sources", []),
        "tool_result": final.get("tool_result"),
        "graph": final.get("graph"),
        "trace": final.get("trace", []),
        "llm_calls": counting.calls,
    }