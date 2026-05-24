from __future__ import annotations

import hashlib
import logging
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    provider: str
    model: str
    dimension: int
    normalized: bool


class EmbeddingDimensionError(ValueError):
    pass


class EmbeddingClient(ABC):
    provider: str
    model: str
    dimension: int
    normalized: bool

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        raise NotImplementedError

    def embed_text(self, text: str) -> EmbeddingResult:
        return self.embed_texts([text])[0]


def normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def validate_dimension(actual: int, expected: int, *, model: str) -> None:
    if actual != expected:
        raise EmbeddingDimensionError(
            f"Embedding dimension mismatch for {model}: expected {expected}, got {actual}. "
            "Update EMBEDDING_DIMENSION and the pgvector column together, or rebuild with a compatible model."
        )


class LocalEmbeddingClient(EmbeddingClient):
    provider = "local"

    def __init__(
        self,
        model: str | None = None,
        fallback_model: str | None = None,
        expected_dimension: int | None = None,
        normalize: bool | None = None,
        device: str | None = None,
        cache_dir: str | None = None,
    ):
        settings = get_settings()
        self.model = model or settings.local_embedding_model
        self.fallback_model = fallback_model if fallback_model is not None else settings.local_embedding_fallback_model
        self.expected_dimension = expected_dimension or settings.embedding_dimension
        self.normalized = settings.embedding_normalize if normalize is None else normalize
        self.device = device or settings.embedding_device
        self.cache_dir = str(cache_dir or settings.embedding_model_cache_dir) if (cache_dir or settings.embedding_model_cache_dir) else None
        self._model = self._load_sentence_transformer(self.model)
        probe = self.embed_text("dimension probe")
        validate_dimension(probe.dimension, self.expected_dimension, model=self.model)
        self.dimension = probe.dimension

    def _load_sentence_transformer(self, model_name: str):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "Local embeddings require the embeddings extra: pip install -e \".[embeddings]\""
            ) from exc

        kwargs = {}
        if self.device and self.device != "auto":
            kwargs["device"] = self.device
        if self.cache_dir:
            kwargs["cache_folder"] = self.cache_dir
        try:
            return SentenceTransformer(model_name, trust_remote_code=True, **kwargs)
        except Exception:
            if not self.fallback_model or model_name == self.fallback_model:
                raise
            logger.warning("Failed to load %s; falling back to %s", model_name, self.fallback_model)
            self.model = self.fallback_model
            return SentenceTransformer(self.fallback_model, trust_remote_code=True, **kwargs)

    def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        if not texts:
            return []
        vectors = self._model.encode(
            texts,
            normalize_embeddings=self.normalized,
            convert_to_numpy=False,
            show_progress_bar=False,
        )
        results: list[EmbeddingResult] = []
        for vector in vectors:
            values = [float(value) for value in vector]
            if self.normalized:
                values = normalize_vector(values)
            dimension = len(values)
            validate_dimension(dimension, self.expected_dimension, model=self.model)
            results.append(
                EmbeddingResult(
                    vector=values,
                    provider=self.provider,
                    model=self.model,
                    dimension=dimension,
                    normalized=self.normalized,
                )
            )
        return results


class OpenAIEmbeddingClient(EmbeddingClient):
    provider = "openai"

    def __init__(
        self,
        model: str | None = None,
        expected_dimension: int | None = None,
        normalize: bool | None = None,
        batch_size: int = 2048,
    ):
        settings = get_settings()
        self.model = model or settings.openai_embedding_model
        self.expected_dimension = expected_dimension or settings.embedding_dimension
        self.normalized = settings.embedding_normalize if normalize is None else normalize
        self.batch_size = batch_size
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI embeddings")
        from openai import OpenAI
        self._client = OpenAI(api_key=settings.openai_api_key)
        # Dimension is determined by the API (we request it via dimensions param)
        self.dimension = self.expected_dimension

    def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        if not texts:
            return []
        all_results: list[EmbeddingResult] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            response = self._client.embeddings.create(
                input=batch,
                model=self.model,
                dimensions=self.expected_dimension,
            )
            for item in response.data:
                values = list(item.embedding)
                if self.normalized:
                    values = normalize_vector(values)
                all_results.append(
                    EmbeddingResult(
                        vector=values,
                        provider=self.provider,
                        model=self.model,
                        dimension=len(values),
                        normalized=self.normalized,
                    )
                )
        return all_results


class MockEmbeddingClient(EmbeddingClient):
    provider = "mock"

    def __init__(self, dimension: int = 1024, model: str = "mock-embedding", normalize: bool = True):
        self.model = model
        self.dimension = dimension
        self.normalized = normalize

    def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> EmbeddingResult:
        values: list[float] = []
        counter = 0
        while len(values) < self.dimension:
            digest = hashlib.sha256(f"{counter}:{text.lower()}".encode("utf-8")).digest()
            values.extend((byte / 127.5) - 1.0 for byte in digest)
            counter += 1
        vector = values[: self.dimension]
        if self.normalized:
            vector = normalize_vector(vector)
        return EmbeddingResult(
            vector=vector,
            provider=self.provider,
            model=self.model,
            dimension=len(vector),
            normalized=self.normalized,
        )
