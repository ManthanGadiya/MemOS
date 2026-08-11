"""Deterministic local embedder.

A dependency-free, deterministic hashing embedder used for development and
tests. It produces stable vectors for identical text, supports token
overlap through n-gram hashing, and requires no network access. It is NOT a
semantic embedder; swap in a real provider for production.
"""

from __future__ import annotations

import hashlib
import re
from typing import List

import numpy as np

from memos.domain.exceptions import EmbeddingError


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class HashEmbedder:
    """Hashing embedder with deterministic n-gram features.

    Strategy: split text into character n-grams (n=3), hash each n-gram to a
    feature index, accumulate signed counts into a vector of ``dimension``,
    then L2-normalize. Identical inputs always produce identical vectors.
    """

    def __init__(self, dimension: int = 256, ngram: int = 3) -> None:
        if dimension <= 0:
            raise EmbeddingError("Embedding dimension must be positive")
        self.dimension = dimension
        self.ngram = ngram

    def _n_grams(self, text: str) -> List[str]:
        lowered = re.sub(r"\s+", " ", text.lower()).strip()
        if not lowered:
            return []
        return [lowered[i : i + self.ngram] for i in range(max(1, len(lowered) - self.ngram + 1))]

    def embed(self, text: str) -> List[float]:
        vector = np.zeros(self.dimension, dtype=np.float64)
        for gram in self._n_grams(text):
            digest = _sha256_hex(gram)
            index = int(digest[:8], 16) % self.dimension
            sign = 1.0 if int(digest[8:16], 16) % 2 == 0 else -1.0
            vector[index] += sign
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm
        return vector.tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.embed(text) for text in texts]


__all__ = ["HashEmbedder"]