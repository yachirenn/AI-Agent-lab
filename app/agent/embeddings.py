from __future__ import annotations

import hashlib
import logging
import os
from typing import Protocol

import httpx
import numpy as np
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

DEFAULT_DIMENSION = 768
DEFAULT_EMBEDDING_MODEL = "gemini-embedding-001"


class EmbeddingError(RuntimeError):
    pass


class Embedder(Protocol):
    def embed_text(self, text: str) -> list[float]: ...
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


class GeminiEmbedder:
    _URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_EMBEDDING_MODEL,
        dimension: int = DEFAULT_DIMENSION,
        timeout: float = 15.0,
    ) -> None:
        self._key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not self._key:
            raise EmbeddingError("GEMINI_API_KEY tidak ditemukan")
        self._model = model
        self._dimension = dimension
        self._http = httpx.Client(timeout=timeout)

    def embed_text(self, text: str) -> list[float]:
        clean = " ".join(text.split())[:2048]
        if not clean:
            return [0.0] * self._dimension

        body = {
            "content": {"parts": [{"text": clean}]},
            "outputDimensionality": self._dimension,
        }
        try:
            resp = self._http.post(
                self._URL.format(model=self._model),
                json=body,
                headers={"x-goog-api-key": self._key},
            )
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"koneksi embedding gagal: {type(exc).__name__}") from None

        if resp.status_code != 200:
            try:
                detail = resp.json().get("error", {}).get("message", "")[:200]
            except Exception:
                detail = resp.text[:200]
            raise EmbeddingError(f"Gemini embedding HTTP {resp.status_code}: {detail}")

        data = resp.json()
        values = data.get("embedding", {}).get("values")
        if not values or len(values) != self._dimension:
            raise EmbeddingError(
                f"dimensi embedding tidak sesuai (diharapkan {self._dimension}, didapat {len(values) if values else 0})"
            )
        return [float(v) for v in values]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        # Single items sequentially or batch
        return [self.embed_text(t) for t in texts]


class MockEmbedder:
    """Embedder deterministik untuk pengujian unit offline tanpa internet atau API key."""

    def __init__(self, dimension: int = DEFAULT_DIMENSION) -> None:
        self.dimension = dimension

    def embed_text(self, text: str) -> list[float]:
        clean = " ".join(text.lower().split())
        if not clean:
            return [0.0] * self.dimension
        # Buat seed dari MD5 hash text agar deterministik
        h = int(hashlib.md5(clean.encode("utf-8")).hexdigest(), 16)
        rng = np.random.default_rng(h % (2**32))
        vec = rng.normal(0, 1, self.dimension)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return [float(x) for x in vec]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(t) for t in texts]


def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    a = np.array(vec1, dtype=np.float64)
    b = np.array(vec2, dtype=np.float64)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def get_embedder() -> Embedder:
    key = os.environ.get("GEMINI_API_KEY")
    if key and key.strip() and not key.startswith("your-"):
        try:
            return GeminiEmbedder(key)
        except Exception as exc:
            logger.warning("gagal inisialisasi GeminiEmbedder, fallback ke MockEmbedder: %s", exc)
    return MockEmbedder()
