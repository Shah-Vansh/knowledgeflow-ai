import threading
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import List, Optional, Tuple

from sentence_transformers import SentenceTransformer

from app.core.config import settings


class EmbeddingProvider(ABC):
    """
    Abstract interface for turning text into vectors.
    Swapping providers should never require touching code outside this file.
    """

    @abstractmethod
    def embed(self, text: str) -> List[float]:
        ...

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        ...


class LocalEmbeddingProvider(EmbeddingProvider):
    """
    Runs entirely on this machine via sentence-transformers.
    No API key, no cost, no rate limits — the model downloads once
    (a few hundred MB) the first time it's used, then runs from a
    local cache.
    """

    _model = None  # loaded lazily, shared across instances

    def __init__(self):
        if LocalEmbeddingProvider._model is None:
            LocalEmbeddingProvider._model = SentenceTransformer(settings.EMBEDDING_MODEL)
        self._model = LocalEmbeddingProvider._model

    def embed(self, text: str) -> List[float]:
        return self._model.encode(text, normalize_embeddings=True).tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        return self._model.encode(texts, normalize_embeddings=True).tolist()


class QueryEmbeddingCache:
    """
    Thread-safe LRU of query vectors (Phase 16). Questions repeat a lot (eval runs,
    experiments, the same question asked again in chat), and embedding one costs a
    model call. Only single-text `embed` calls are cached; document chunks go through
    `embed_batch` and are embedded once anyway. Per process, so it empties on restart.
    """

    def __init__(self, maxsize: int):
        self.maxsize = maxsize
        self._data: "OrderedDict[Tuple[str, str], Tuple[float, ...]]" = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: Tuple[str, str]) -> Optional[List[float]]:
        with self._lock:
            vector = self._data.get(key)
            if vector is None:
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return list(vector)  # a fresh list: callers can't corrupt the cached copy

    def put(self, key: Tuple[str, str], vector: List[float]) -> None:
        if self.maxsize <= 0:
            return
        with self._lock:
            self._data[key] = tuple(vector)
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self.hits = 0
            self.misses = 0


query_cache = QueryEmbeddingCache(settings.EMBED_CACHE_SIZE)


class CachedEmbeddingProvider(EmbeddingProvider):
    """Wraps a provider; `embed` goes through the query cache, `embed_batch` does not."""

    def __init__(self, inner: EmbeddingProvider, cache: QueryEmbeddingCache, model_name: str):
        self.inner = inner
        self.cache = cache
        self.model_name = model_name

    def embed(self, text: str) -> List[float]:
        if self.cache.maxsize <= 0:
            return self.inner.embed(text)
        key = (self.model_name, text)
        vector = self.cache.get(key)
        if vector is None:
            vector = self.inner.embed(text)
            self.cache.put(key, vector)
        return vector

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return self.inner.embed_batch(texts)


def get_embedding_provider() -> EmbeddingProvider:
    return CachedEmbeddingProvider(LocalEmbeddingProvider(), query_cache, settings.EMBEDDING_MODEL)