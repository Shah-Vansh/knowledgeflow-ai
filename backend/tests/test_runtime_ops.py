"""Production runtime (Phase 16): log redaction + JSON logs, readiness, metrics, the query-embedding cache."""
import io
import json
import logging
import threading

import pytest
from fastapi.testclient import TestClient

from app.api import health as health_module
from app.core import metrics
from app.core.config import settings
from app.core.logging import (JsonFormatter, RedactingTextFormatter, RequestIdFilter, build_formatter,
                              redact, request_id_var)
from app.main import app
from app.rag.embeddings import CachedEmbeddingProvider, EmbeddingProvider, QueryEmbeddingCache

client = TestClient(app)

# Secret-shaped strings are assembled at runtime so scripts/scan_secrets.py
# (which reads the source) never mistakes these fake fixtures for real leaks.
FAKE_GROQ = "gsk" + "_ABCDEFGHIJKLMNOPQRSTUVWX123"
FAKE_SECRET = "abcdef" * 5 + "12"
FAKE_DB_URL = "postgresql://kf" + ":" + "topsecretpw" + "@db/kf"
FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIiwiZXhwIjo5OTk5OTk5OTk5fQ.c2lnbmF0dXJlLXZhbHVl"


# ------------------------------------------------------------------ redaction
@pytest.mark.parametrize("raw, secret", [
    ("connecting to postgresql://kf:hunter2pass@localhost:5432/db", "hunter2pass"),
    ("headers={'Authorization': 'Bearer abc.def.ghi'}", "abc.def.ghi"),
    ("Authorization: Bearer s3cr3tT0ken", "s3cr3tT0ken"),
    (f"token was {FAKE_JWT} ok", FAKE_JWT),
    (f"GROQ key {FAKE_GROQ} loaded", FAKE_GROQ),
    ('{"email": "a@b.com", "password": "correct-horse-battery"}', "correct-horse-battery"),
    ("login password=letmein12345 for user", "letmein12345"),
    ("JWT_" + f"SECRET={FAKE_SECRET}", FAKE_SECRET),
    ("api_key: sk-proj-1234567890abcdefghij", "sk-proj-1234567890abcdefghij"),
    ("METRICS_TOKEN=mt-0123456789abcdefghijkl", "mt-0123456789abcdefghijkl"),
])
def test_redact_masks_secrets(raw, secret):
    cleaned = redact(raw)
    assert secret not in cleaned
    assert "[REDACTED]" in cleaned


@pytest.mark.parametrize("plain", [
    "Ingested 12 chunks for report.pdf in 3.2s",
    "max_tokens=500 temperature=0.2",
    "GET /documents/{document_id}/chunks -> 200 in 12 ms",
    "user 7 joined workspace 3 as viewer",
])
def test_redact_leaves_ordinary_text_alone(plain):
    assert redact(plain) == plain


def _record(msg, *args, exc_info=None, **extra):
    record = logging.LogRecord("kf.test", logging.INFO, __file__, 1, msg, args, exc_info)
    for key, value in extra.items():
        setattr(record, key, value)
    RequestIdFilter().filter(record)
    return record


def test_json_formatter_emits_one_redacted_object_with_request_id():
    token = request_id_var.set("req-123")
    try:
        record = _record("login for %s with Bearer %s", "a@b.com", "tok3n-value", route="/auth/login", status=401)
    finally:
        request_id_var.reset(token)
    line = JsonFormatter().format(record)
    assert "\n" not in line
    entry = json.loads(line)
    assert entry["level"] == "INFO" and entry["logger"] == "kf.test"
    assert entry["request_id"] == "req-123"
    assert entry["route"] == "/auth/login" and entry["status"] == 401
    assert "tok3n-value" not in line and "[REDACTED]" in entry["message"]


def test_json_formatter_redacts_exceptions():
    try:
        raise RuntimeError(f"could not connect to {FAKE_DB_URL}")
    except RuntimeError:
        import sys
        record = _record("failed", exc_info=sys.exc_info())
    line = JsonFormatter().format(record)
    assert "topsecretpw" not in line and "RuntimeError" in json.loads(line)["exception"]


def test_text_formatter_redacts_too():
    formatter = build_formatter("text")
    assert isinstance(formatter, RedactingTextFormatter)
    line = formatter.format(_record("Bearer %s", FAKE_JWT))
    assert FAKE_JWT not in line and "[REDACTED]" in line


def test_request_id_reaches_log_lines_of_a_request(caplog):
    caplog.set_level(logging.INFO, logger="kf.access")
    client.get("/documents", headers={"X-Request-ID": "trace-abc-1"})
    lines = [r for r in caplog.records if r.name == "kf.access" and getattr(r, "route", "") == "/documents"]
    assert lines, "no access log line"
    assert lines[-1].request_id == "trace-abc-1"
    assert lines[-1].status == 200 and lines[-1].method == "GET"


def test_access_log_uses_route_templates_not_raw_paths(caplog):
    caplog.set_level(logging.INFO, logger="kf.access")
    client.get("/documents/2000000000/chunks?secret=1")
    routes = [getattr(r, "route", "") for r in caplog.records if r.name == "kf.access"]
    assert "/documents/{document_id}/chunks" in routes
    assert not any("2000000000" in r or "secret" in r for r in routes)


def test_setup_logging_is_idempotent(monkeypatch):
    from app.core.logging import setup_logging

    root = logging.getLogger()
    before = [h for h in root.handlers if getattr(h, "_kf_handler", False)]
    setup_logging()
    setup_logging()
    after = [h for h in root.handlers if getattr(h, "_kf_handler", False)]
    assert len(after) == 1 and len(before) <= 1


# ------------------------------------------------------------------ health
def test_liveness_never_needs_the_database(monkeypatch):
    monkeypatch.setattr(health_module, "check_db_connection", lambda: False)
    assert client.get("/health/live").json() == {"status": "alive"}


def test_ready_when_database_up_and_migrated():
    response = client.get("/health/ready")
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ready", "checks": {"database": True, "migrations": True}}


def test_not_ready_when_database_down(monkeypatch):
    monkeypatch.setattr(health_module, "check_db_connection", lambda: False)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": False, "migrations": False}


def test_not_ready_when_migrations_are_behind(monkeypatch):
    monkeypatch.setattr(health_module, "current_migration", lambda: "0010")
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["migrations"] is False


def test_expected_head_matches_the_newest_migration():
    assert health_module.expected_migration_head() == "0011"


# ------------------------------------------------------------------ metrics
def test_metrics_open_in_dev_and_count_requests_by_template():
    metrics.reset_all()
    client.get("/documents/2000000000/chunks")
    client.get("/documents/2000000001/chunks")
    body = client.get("/metrics").text
    assert 'kf_http_requests_total{method="GET",route="/documents/{document_id}/chunks",status="200"} 2' in body
    assert "# TYPE kf_http_request_duration_seconds histogram" in body
    assert 'kf_jobs{status="queued"}' in body
    assert "kf_embedding_cache_entries" in body
    assert "2000000000" not in body


def test_metrics_require_the_token_when_set(monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", "m" * 12 + "0123456789ab")
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    ok = client.get("/metrics", headers={"Authorization": f"Bearer {'m' * 12}0123456789ab"})
    assert ok.status_code == 200 and "kf_http_requests_total" in ok.text


def test_metrics_disabled_when_auth_on_without_token(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "METRICS_TOKEN", "")
    response = client.get("/metrics")
    assert response.status_code == 404 and "METRICS_TOKEN" in response.json()["detail"]


def test_short_metrics_token_is_a_configuration_problem(monkeypatch):
    from app.core.security import security_problems

    monkeypatch.setattr(settings, "METRICS_TOKEN", "short")
    assert any("METRICS_TOKEN" in p for p in security_problems(settings))


def test_histogram_buckets_are_cumulative():
    h = metrics.Histogram("t_seconds", "test", buckets=(0.1, 1.0))
    for v in (0.05, 0.5, 5.0):
        h.observe(v, route="/x")
    text = "\n".join(h.render())
    assert 't_seconds_bucket{route="/x",le="0.1"} 1' in text
    assert 't_seconds_bucket{route="/x",le="1"} 2' in text
    assert 't_seconds_bucket{route="/x",le="+Inf"} 3' in text
    assert 't_seconds_count{route="/x"} 3' in text


def test_label_values_are_escaped():
    c = metrics.Counter("t_total", "test")
    c.inc(route='a"b\\c\nd')
    assert 't_total{route="a\\"b\\\\c\\nd"} 1' in "\n".join(c.render())


# ------------------------------------------------------------------ embedding cache
class CountingEmbedder(EmbeddingProvider):
    def __init__(self):
        self.calls = 0

    def embed(self, text):
        self.calls += 1
        return [float(len(text)), float(self.calls)]

    def embed_batch(self, texts):
        self.calls += len(texts)
        return [[float(len(t)), 0.0] for t in texts]


def test_cache_hits_skip_the_model():
    inner = CountingEmbedder()
    provider = CachedEmbeddingProvider(inner, QueryEmbeddingCache(8), "m")
    first = provider.embed("what grew?")
    second = provider.embed("what grew?")
    assert first == second and inner.calls == 1
    assert provider.cache.hits == 1 and provider.cache.misses == 1


def test_cache_key_is_the_exact_text_and_model():
    inner = CountingEmbedder()
    cache = QueryEmbeddingCache(8)
    a = CachedEmbeddingProvider(inner, cache, "model-a")
    b = CachedEmbeddingProvider(inner, cache, "model-b")
    a.embed("q")
    a.embed("q ")
    b.embed("q")
    assert inner.calls == 3


def test_cache_evicts_least_recently_used():
    inner = CountingEmbedder()
    provider = CachedEmbeddingProvider(inner, QueryEmbeddingCache(2), "m")
    provider.embed("a")
    provider.embed("b")
    provider.embed("a")      # a is now most recent
    provider.embed("c")      # evicts b
    assert len(provider.cache) == 2
    calls = inner.calls
    provider.embed("a")
    assert inner.calls == calls
    provider.embed("b")
    assert inner.calls == calls + 1


def test_cached_vector_cannot_be_corrupted_by_a_caller():
    provider = CachedEmbeddingProvider(CountingEmbedder(), QueryEmbeddingCache(4), "m")
    vector = provider.embed("x")
    vector[0] = 999.0
    assert provider.embed("x")[0] != 999.0


def test_cache_size_zero_disables_it():
    inner = CountingEmbedder()
    provider = CachedEmbeddingProvider(inner, QueryEmbeddingCache(0), "m")
    provider.embed("q")
    provider.embed("q")
    assert inner.calls == 2 and len(provider.cache) == 0


def test_batch_embedding_bypasses_the_cache():
    inner = CountingEmbedder()
    provider = CachedEmbeddingProvider(inner, QueryEmbeddingCache(4), "m")
    provider.embed_batch(["a", "b"])
    assert len(provider.cache) == 0 and inner.calls == 2


def test_cache_is_thread_safe():
    provider = CachedEmbeddingProvider(CountingEmbedder(), QueryEmbeddingCache(16), "m")
    errors = []

    def hammer(i):
        try:
            for n in range(300):
                provider.embed(f"q{(i + n) % 40}")
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and len(provider.cache) <= 16
    assert provider.cache.hits + provider.cache.misses == 8 * 300


def test_real_provider_is_cached():
    from app.rag.embeddings import get_embedding_provider, query_cache

    provider = get_embedding_provider()
    assert isinstance(provider, CachedEmbeddingProvider) and provider.cache is query_cache
    question = "phase 16 cache check: which region grew?"
    first = provider.embed(question)
    hits = query_cache.hits
    assert get_embedding_provider().embed(question) == first
    assert query_cache.hits == hits + 1
    assert len(first) == settings.EMBEDDING_DIM


def test_json_logs_drop_uvicorn_colour_codes():
    record = _record("Uvicorn running", color_message="\x1b[1mUvicorn running\x1b[0m")
    assert "color_message" not in json.loads(JsonFormatter().format(record))
