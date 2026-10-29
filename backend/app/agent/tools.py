"""
Deterministic tools for the agent (Phase 11). None of them runs model-written code
or SQL: the calculator walks a restricted syntax tree, the metadata tool runs a fixed
set of parameterized queries, and document search is a filename match. Every database
tool is scoped to one workspace.
"""
import ast
import math
import operator
import re
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document, Entity, Relationship

Number = Union[int, float]

# ----------------------------------------------------------------- calculator

MAX_EXPR_CHARS = 200
MAX_EXPR_NODES = 60
MAX_RESULT = 1e30
MAX_EXPONENT = 100


class CalculatorError(ValueError):
    pass


_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _check_result(value: Any) -> Number:
    if isinstance(value, complex):
        raise CalculatorError("the result is not a real number")
    if isinstance(value, float) and not math.isfinite(value):
        raise CalculatorError("the result is not a finite number")
    if abs(value) > MAX_RESULT:
        raise CalculatorError("the result is too large")
    return value


def _evaluate(node: ast.AST) -> Number:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise CalculatorError("only numbers are allowed")
        return _check_result(node.value)

    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _check_result(_UNARY[type(node.op)](_evaluate(node.operand)))

    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise CalculatorError("the exponent is too large")
        try:
            return _check_result(_BINARY[type(node.op)](left, right))
        except ZeroDivisionError:
            raise CalculatorError("division by zero")
        except OverflowError:
            raise CalculatorError("the result is too large")

    raise CalculatorError("only numbers and + - * / // % ** ( ) are allowed")


def safe_eval(expression: str) -> Number:
    """Evaluates plain arithmetic. Anything else (names, calls, attributes, strings) is rejected."""
    if not isinstance(expression, str):
        raise CalculatorError("the expression must be text")

    text = expression.strip().replace("^", "**").replace("×", "*").replace("÷", "/")
    text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)       # 1,000 -> 1000
    if not text:
        raise CalculatorError("the expression is empty")
    if len(text) > MAX_EXPR_CHARS:
        raise CalculatorError("the expression is too long")

    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        raise CalculatorError("this is not a valid arithmetic expression")

    if sum(1 for _ in ast.walk(tree)) > MAX_EXPR_NODES:
        raise CalculatorError("the expression is too complex")

    return _evaluate(tree.body)


def format_number(value: Number) -> str:
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.10g}"
    return str(value)


# ------------------------------------------------------------------- metadata

METADATA_QUERIES = ("count_documents", "list_documents", "count_chunks", "document_stats")
FILE_TYPES = ("pdf", "txt")
STATUSES = ("processed", "processing", "failed")
MAX_LIST_LIMIT = 20


class MetadataQueryError(ValueError):
    pass


def _clean_choice(args: Dict[str, Any], key: str, allowed: tuple) -> Optional[str]:
    value = args.get(key)
    if value is None or value == "":
        return None
    value = str(value).strip().lower()
    if value not in allowed:
        raise MetadataQueryError(f"{key} must be one of: {', '.join(allowed)}")
    return value


def _active_documents(db: Session, workspace_id: int):
    return db.query(Document).filter(
        Document.workspace_id == workspace_id, Document.deleted_at.is_(None)
    )


def run_metadata_query(
    db: Session, workspace_id: int, query_name: str, args: Optional[Dict[str, Any]] = None
) -> dict:
    if query_name not in METADATA_QUERIES:
        raise MetadataQueryError(f"unknown metadata query; allowed: {', '.join(METADATA_QUERIES)}")
    if args is not None and not isinstance(args, dict):
        raise MetadataQueryError("args must be an object")
    args = args or {}

    file_type = _clean_choice(args, "file_type", FILE_TYPES)
    status = _clean_choice(args, "status", STATUSES)
    filters = {k: v for k, v in (("file_type", file_type), ("status", status)) if v}

    if query_name in ("count_documents", "list_documents"):
        query = _active_documents(db, workspace_id)
        if file_type:
            query = query.filter(Document.source_type == file_type)
        if status:
            query = query.filter(Document.status == status)

        if query_name == "count_documents":
            return {"query": query_name, "filters": filters, "count": query.count()}

        try:
            limit = int(args.get("limit", 10))
        except (TypeError, ValueError):
            raise MetadataQueryError("limit must be a number")
        limit = max(1, min(limit, MAX_LIST_LIMIT))

        documents = query.order_by(Document.uploaded_at.desc(), Document.id.desc()).limit(limit).all()
        return {
            "query": query_name,
            "filters": filters,
            "documents": [
                {
                    "id": d.id,
                    "filename": d.filename,
                    "source_type": d.source_type,
                    "page_count": d.page_count,
                    "status": d.status,
                }
                for d in documents
            ],
        }

    if query_name == "count_chunks":
        count = (
            db.query(func.count(Chunk.id))
            .join(Document, Chunk.document_id == Document.id)
            .filter(Document.workspace_id == workspace_id, Document.deleted_at.is_(None))
            .scalar()
        )
        return {"query": query_name, "filters": {}, "count": count}

    # document_stats
    documents = _active_documents(db, workspace_id).count()
    pages = (
        db.query(func.coalesce(func.sum(Document.page_count), 0))
        .filter(Document.workspace_id == workspace_id, Document.deleted_at.is_(None))
        .scalar()
    )
    chunks = (
        db.query(func.count(Chunk.id))
        .join(Document, Chunk.document_id == Document.id)
        .filter(Document.workspace_id == workspace_id, Document.deleted_at.is_(None))
        .scalar()
    )
    entities = db.query(func.count(Entity.id)).filter(Entity.workspace_id == workspace_id).scalar()
    relationships = (
        db.query(func.count(Relationship.id)).filter(Relationship.workspace_id == workspace_id).scalar()
    )
    return {
        "query": query_name,
        "filters": {},
        "documents": documents,
        "total_pages": int(pages or 0),
        "chunks": chunks,
        "entities": entities,
        "relationships": relationships,
    }


def format_metadata_answer(result: dict) -> str:
    name = result["query"]
    filters = result.get("filters") or {}
    qualifier = ""
    if filters.get("file_type"):
        qualifier += f" {filters['file_type'].upper()}"
    if filters.get("status"):
        qualifier += f" ({filters['status']})"

    if name == "count_documents":
        n = result["count"]
        return f"This workspace has {n}{qualifier} document{'s' if n != 1 else ''}."
    if name == "count_chunks":
        n = result["count"]
        return f"This workspace has {n} indexed chunk{'s' if n != 1 else ''}."
    if name == "list_documents":
        documents = result["documents"]
        if not documents:
            return f"No{qualifier} documents in this workspace."
        lines = [
            f"- {d['filename']}"
            + (f" ({d['page_count']} pages)" if d["page_count"] else "")
            for d in documents
        ]
        return f"Most recent{qualifier} documents:\n" + "\n".join(lines)

    return (
        f"This workspace has {result['documents']} document(s), {result['total_pages']} page(s) "
        f"in total, {result['chunks']} chunk(s), {result['entities']} graph entit"
        f"{'y' if result['entities'] == 1 else 'ies'} and {result['relationships']} relationship(s)."
    )


# ------------------------------------------------------------ document search

MAX_SEARCH_TERMS = 5


def search_documents(db: Session, workspace_id: int, query: str, limit: int = 10) -> dict:
    """Finds documents whose FILENAME contains every search word (case-insensitive)."""
    terms = [t for t in re.findall(r"[a-z0-9]+", str(query).lower()) if len(t) >= 2][:MAX_SEARCH_TERMS]
    if not terms:
        raise MetadataQueryError("no usable search words")

    documents_query = _active_documents(db, workspace_id)
    for term in terms:
        documents_query = documents_query.filter(
            func.lower(Document.filename).contains(term, autoescape=True)
        )
    documents = documents_query.order_by(Document.uploaded_at.desc(), Document.id.desc()).limit(limit).all()

    return {
        "query": query,
        "terms": terms,
        "documents": [
            {
                "id": d.id,
                "filename": d.filename,
                "source_type": d.source_type,
                "page_count": d.page_count,
            }
            for d in documents
        ],
    }


def format_document_search_answer(result: dict) -> str:
    documents = result["documents"]
    words = " ".join(result["terms"])
    if not documents:
        return f"No document in this workspace has a filename matching \"{words}\"."
    lines = [
        f"- {d['filename']}" + (f" ({d['page_count']} pages)" if d["page_count"] else "")
        for d in documents
    ]
    return f"Found {len(documents)} document(s) with a filename matching \"{words}\":\n" + "\n".join(lines)