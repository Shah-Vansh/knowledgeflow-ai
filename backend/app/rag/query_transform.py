import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional

from app.core.config import settings
from app.rag.llm import LLMProvider

logger = logging.getLogger(__name__)

# rewrite:     one clearer, self-contained search query
# expand:      keywords/synonyms -> sparse search, OR semantics
# multi_query: several paraphrases, each searched
# hyde:        a hypothetical answer passage, embedded instead of the question
ALLOWED_TRANSFORMS = ("rewrite", "expand", "multi_query", "hyde")

MAX_QUERY_CHARS = 300
MAX_HYDE_CHARS = 1000
MAX_KEYWORDS = 10
MAX_KEYWORD_CHARS = 60


@dataclass
class TransformResult:
    original: str
    requested: List[str]
    rewrite: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    variants: List[str] = field(default_factory=list)
    hyde: Optional[str] = None
    fallback_used: bool = False
    error: Optional[str] = None
    elapsed_ms: float = 0.0


@dataclass
class SearchJob:
    label: str    # "original", "rewrite", "variant 1", "hyde", "expand"
    kind: str     # "original" | "rewrite" | "variant" | "hyde" | "expand"
    text: str     # query text / hypothetical passage / joined keywords
    dense: bool
    sparse: bool
    terms: List[str] = field(default_factory=list)  # expand only: OR'd terms


def normalize_transforms(names: Optional[List[str]]) -> List[str]:
    """Validates strategy names; returns them deduplicated, in canonical order."""
    if not names:
        return []

    cleaned = [str(n).strip().lower() for n in names if str(n).strip()]
    unknown = sorted({n for n in cleaned if n not in ALLOWED_TRANSFORMS})
    if unknown:
        raise ValueError(
            f"Unknown transform(s): {', '.join(unknown)}. "
            f"Allowed: {', '.join(ALLOWED_TRANSFORMS)}"
        )

    return [t for t in ALLOWED_TRANSFORMS if t in cleaned]


def _normalize(text: str) -> str:
    return " ".join(text.lower().split()).rstrip("?.! ")


def build_prompt(question: str, requested: List[str], variant_count: int) -> str:
    spec = []
    if "rewrite" in requested:
        spec.append(
            '"rewrite": string - one clearer, self-contained search query that keeps '
            "the exact meaning of the question"
        )
    if "expand" in requested:
        spec.append(
            '"keywords": list of 5 to 10 strings - important terms, synonyms and '
            "alternative wordings a relevant passage might contain"
        )
    if "multi_query" in requested:
        spec.append(
            f'"variants": list of {variant_count} strings - differently worded '
            "versions of the question"
        )
    if "hyde" in requested:
        spec.append(
            '"hyde": string - a short passage (2 to 4 sentences) written like text from '
            "a document that would answer the question. It may be invented; it is only "
            "used to search"
        )

    keys = ", ".join(line.split(":")[0] for line in spec)
    spec_block = "\n".join(f"- {line}" for line in spec)

    return f"""You help a document search system turn a user's question into better search inputs.

Rules:
- Reply with ONLY one JSON object. No markdown, no commentary.
- Use exactly these keys: {keys}
- Keep the original meaning. Do not add specific facts the question does not imply.

Keys:
{spec_block}

Question: {question}
JSON:"""


def _extract_json(raw: Any) -> dict:
    if not isinstance(raw, str):
        raise ValueError("model returned no text")

    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in model output")

    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("model output JSON is not an object")
    return data


def _clean_text(value: Any, limit: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text[:limit] if text else None


def _clean_keywords(value: Any) -> List[str]:
    if isinstance(value, str):
        value = re.split(r"[,;\n]", value)
    if not isinstance(value, list):
        return []

    seen, cleaned = set(), []
    for item in value:
        if not isinstance(item, str):
            continue
        term = " ".join(item.split()).strip("\"'`").lstrip("-").strip()
        term = term[:MAX_KEYWORD_CHARS]
        if not any(ch.isalnum() for ch in term):
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(term)
        if len(cleaned) >= MAX_KEYWORDS:
            break
    return cleaned


def _clean_variants(value: Any, original: str, limit: int) -> List[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []

    seen = {_normalize(original)}
    cleaned = []
    for item in value:
        text = _clean_text(item, MAX_QUERY_CHARS)
        if text is None:
            continue
        key = _normalize(text)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def transform_query(
    llm: LLMProvider,
    question: str,
    requested: List[str],
    variant_count: Optional[int] = None,
) -> TransformResult:
    """
    ONE LLM call produces every requested transformation as JSON.

    Fails open: if the call errors or the output is unusable, the result is
    flagged (fallback_used=True) with every field empty, so the pipeline simply
    searches the original query. A failed transformation never breaks answering.
    """
    requested = list(requested)
    result = TransformResult(original=question, requested=requested)
    if not requested:
        return result

    count = variant_count or settings.MULTI_QUERY_COUNT
    started = time.perf_counter()

    try:
        raw = llm.generate(build_prompt(question, requested, count), temperature=0.0)
        data = _extract_json(raw)

        # Only fields for strategies that were actually requested are used.
        if "rewrite" in requested:
            result.rewrite = _clean_text(data.get("rewrite"), MAX_QUERY_CHARS)
        if "expand" in requested:
            result.keywords = _clean_keywords(data.get("keywords"))
        if "multi_query" in requested:
            result.variants = _clean_variants(data.get("variants"), question, count)
        if "hyde" in requested:
            result.hyde = _clean_text(data.get("hyde"), MAX_HYDE_CHARS)

        if not (result.rewrite or result.keywords or result.variants or result.hyde):
            raise ValueError("model returned no usable output for the requested strategies")

    except Exception as exc:
        logger.warning("Query transformation failed; using the original query only: %s", exc)
        result.rewrite = None
        result.keywords = []
        result.variants = []
        result.hyde = None
        result.fallback_used = True
        result.error = f"{type(exc).__name__}: {exc}"[:300]

    result.elapsed_ms = (time.perf_counter() - started) * 1000
    return result


def plan_search_jobs(result: TransformResult) -> List[SearchJob]:
    """
    Turns a TransformResult into the searches to run. The original question is
    ALWAYS job 1 (dense + sparse). Others:
      rewrite / variants -> dense + sparse
      hyde               -> dense only (a hypothetical passage is a bad keyword query)
      expand             -> sparse only, OR semantics across the keywords
    A rewrite or variant that duplicates an existing query is skipped.
    """
    jobs = [SearchJob(label="original", kind="original", text=result.original, dense=True, sparse=True)]
    seen = {_normalize(result.original)}

    if result.rewrite and _normalize(result.rewrite) not in seen:
        seen.add(_normalize(result.rewrite))
        jobs.append(SearchJob(label="rewrite", kind="rewrite", text=result.rewrite, dense=True, sparse=True))

    for number, variant in enumerate(result.variants, start=1):
        key = _normalize(variant)
        if key in seen:
            continue
        seen.add(key)
        jobs.append(SearchJob(
            label=f"variant {number}", kind="variant", text=variant, dense=True, sparse=True
        ))

    if result.hyde:
        jobs.append(SearchJob(label="hyde", kind="hyde", text=result.hyde, dense=True, sparse=False))

    if result.keywords:
        jobs.append(SearchJob(
            label="expand", kind="expand", text=", ".join(result.keywords),
            dense=False, sparse=True, terms=list(result.keywords),
        ))

    return jobs