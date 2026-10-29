"""
The agent's router (Phase 11): ONE LLM call that picks which tool should handle a
question. Its output is validated strictly, and anything wrong or unusable defaults to
"rag" (plain grounded retrieval), so a flaky router degrades to the normal pipeline.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from app.agent.tools import METADATA_QUERIES
from app.rag.json_utils import extract_json_object
from app.rag.llm import LLMProvider

logger = logging.getLogger(__name__)

ROUTES = ("rag", "graph", "document_search", "metadata", "calculator")
MAX_FIELD_CHARS = 200


@dataclass
class RouteDecision:
    route: str = "rag"
    expression: Optional[str] = None
    query: Optional[str] = None
    args: Dict[str, Any] = field(default_factory=dict)
    fallback_used: bool = False
    error: Optional[str] = None
    elapsed_ms: float = 0.0


def build_router_prompt(question: str) -> str:
    queries = "|".join(METADATA_QUERIES)
    return f"""You route a user's question for a document question-answering system. Choose exactly one route.

Routes:
- "rag": questions about the CONTENT of the documents (facts, explanations, summaries, who/what/why). This is the default.
- "graph": questions about RELATIONSHIPS between named things ("How is X related to Y?", "What connects A and B?", "Who worked with X?").
- "document_search": looking for a FILE by its name ("Do I have a file about budget?", "Find the document called report").
- "metadata": questions about the library itself, such as counts or lists of documents or chunks ("How many PDFs are uploaded?", "List my latest documents", "How many pages in total?").
- "calculator": pure arithmetic where EVERY number is written in the question itself ("What is 15% of 240?" -> expression "0.15 * 240"). If a number must come from the documents, use "rag".

Reply with ONLY one JSON object, no markdown. Include only the fields the route needs:
{{"route": "<route>", "expression": "<arithmetic using digits and + - * / ** ( ) only; convert percentages to decimals>", "query": "<search words for document_search, or one of {queries} for metadata>", "args": {{"file_type": "pdf or txt (optional)", "status": "processed, processing or failed (optional)", "limit": 10}}}}
If you are unsure, use "rag".

Question: {question}
JSON:"""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required for this route")
    text = " ".join(value.split())
    if len(text) > MAX_FIELD_CHARS:
        raise ValueError(f"{name} is too long")
    return text


def parse_route(raw: Any) -> RouteDecision:
    """Validates router output; raises ValueError when it can't be used."""
    data = extract_json_object(raw)

    route = str(data.get("route", "")).strip().lower().replace(" ", "_").replace("-", "_")
    if route not in ROUTES:
        raise ValueError(f"unknown route {route!r}; allowed: {', '.join(ROUTES)}")

    decision = RouteDecision(route=route)

    if route == "calculator":
        decision.expression = _text(data.get("expression"), "expression")
    elif route == "document_search":
        decision.query = _text(data.get("query"), "query")
    elif route == "metadata":
        query = _text(data.get("query"), "query").lower()
        if query not in METADATA_QUERIES:
            raise ValueError(f"unknown metadata query {query!r}; allowed: {', '.join(METADATA_QUERIES)}")
        decision.query = query
        args = data.get("args")
        decision.args = args if isinstance(args, dict) else {}

    return decision


def decide_route(llm: LLMProvider, question: str) -> RouteDecision:
    """Never raises: any failure is reported on the decision and the route defaults to rag."""
    started = time.perf_counter()
    try:
        decision = parse_route(llm.generate(build_router_prompt(question), temperature=0.0))
    except Exception as exc:
        logger.warning("Router failed; defaulting to rag: %s", exc)
        decision = RouteDecision(route="rag", fallback_used=True, error=f"{type(exc).__name__}: {exc}"[:300])
    decision.elapsed_ms = (time.perf_counter() - started) * 1000
    return decision