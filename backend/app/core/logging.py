"""
Logging setup (Phase 16): plain text for development, one JSON object per line
for production (LOG_FORMAT=json), and secret redaction in BOTH formats.

Every line carries the request id of the HTTP request that produced it (set by
the middleware in app/core/http.py through a context variable), so a single
request can be followed through the logs.

Redaction is a safety net, not a licence to log secrets: bearer tokens, JWTs,
passwords in URLs or key=value pairs and provider API keys are masked even if a
log call (or an exception message) accidentally includes them.
"""
import contextvars
import json
import logging
import re
import sys
from datetime import datetime, timezone

from app.core.config import settings

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

REDACTED = "[REDACTED]"
_REDACTIONS = (
    # scheme://user:<pw>@host -> scheme://user:[REDACTED]@host
    (re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://[^:/\s@]+:)[^@\s/]+@"), r"\1" + REDACTED + "@"),
    # Authorization: Bearer xxx / Authorization=xxx
    (re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?)(?:bearer\s+)?[^\s\"',}]+"), r"\1" + REDACTED),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1" + REDACTED),
    # JSON Web Tokens anywhere
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*"), REDACTED),
    # provider keys (Groq gsk_..., OpenAI-style sk-...)
    (re.compile(r"\b(?:gsk|sk)[_-][A-Za-z0-9_-]{16,}"), REDACTED),
    # password=..., "api_key": "...", secret: ...
    (re.compile(
        r"(?i)\b((?:password|passwd|pwd|secret|jwt_secret|api[_-]?key|access[_-]?token|"
        r"refresh[_-]?token|token|metrics_token)[\"']?\s*[:=]\s*[\"']?)[^\s\"',&}]+"),
     r"\1" + REDACTED),
)


def redact(text: str) -> str:
    if not text:
        return text
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        return True


class RedactingTextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message", "asctime", "request_id",
    "color_message",  # uvicorn's copy of the message with terminal colour codes
}


class JsonFormatter(logging.Formatter):
    """One JSON object per line: time, level, logger, message, request_id, extras, exception."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "request_id": getattr(record, "request_id", request_id_var.get()),
        }
        for name, value in vars(record).items():  # logger.info("...", extra={"route": ...})
            if name not in _RESERVED and not name.startswith("_"):
                entry[name] = redact(value) if isinstance(value, str) else value
        if record.exc_info:
            entry["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry, default=str, ensure_ascii=False)


def build_formatter(fmt: str) -> logging.Formatter:
    if (fmt or "").strip().lower() == "json":
        return JsonFormatter()
    return RedactingTextFormatter("%(asctime)s | %(levelname)-8s | %(name)s | %(request_id)s | %(message)s")


def setup_logging() -> None:
    """Idempotent: replaces only the handler this function installed before."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_kf_handler", False):
            root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler._kf_handler = True
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(build_formatter(settings.LOG_FORMAT))
    root.addHandler(handler)
    root.setLevel(settings.LOG_LEVEL)

    if settings.LOG_FORMAT.strip().lower() == "json":
        # Route uvicorn's own loggers through the JSON handler; our access log
        # (app/core/http.py) replaces uvicorn's, which would log raw query strings.
        for name in ("uvicorn", "uvicorn.error"):
            logger = logging.getLogger(name)
            logger.handlers = []
            logger.propagate = True
        logging.getLogger("uvicorn.access").disabled = True
