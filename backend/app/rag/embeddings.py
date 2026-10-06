from abc import ABC, abstractmethod
from typing import List

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


def get_embedding_provider() -> EmbeddingProvider:
    return LocalEmbeddingProvider()