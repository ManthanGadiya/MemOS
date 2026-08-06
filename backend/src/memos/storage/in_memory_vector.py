"""In-memory vector store for development and testing.

Implements :class:`memos.storage.protocols.VectorStore` using numpy cosine
similarity. Qdrant is the production adapter and satisfies the same protocol.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from memos.domain.exceptions import StorageError


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two dense vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    va = np.asarray(a, dtype=np.float64)
    vb = np.asarray(b, dtype=np.float64)
    na = np.linalg.norm(va)
    nb = np.linalg.norm(vb)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


class InMemoryVectorStore:
    """Thread-safe in-memory vector store."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._vectors: Dict[str, List[float]] = {}
        self._payloads: Dict[str, Dict[str, Any]] = {}

    def upsert(self, memory_id: str, vector: List[float], payload: Dict[str, Any]) -> None:
        with self._lock:
            self._vectors[memory_id] = list(vector)
            self._payloads[memory_id] = payload

    def delete(self, memory_id: str) -> None:
        with self._lock:
            self._vectors.pop(memory_id, None)
            self._payloads.pop(memory_id, None)

    def search(
        self,
        vector: List[float],
        top_k: int = 10,
        filter_payload: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[str, float]]:
        with self._lock:
            scored: List[Tuple[str, float]] = []
            for memory_id, stored in self._vectors.items():
                if filter_payload:
                    payload = self._payloads.get(memory_id, {})
                    if not all(payload.get(k) == v for k, v in filter_payload.items()):
                        continue
                scored.append((memory_id, cosine_similarity(vector, stored)))
            scored.sort(key=lambda pair: pair[1], reverse=True)
            return scored[:top_k]

    def clear(self) -> None:
        with self._lock:
            self._vectors.clear()
            self._payloads.clear()

    def close(self) -> None:
        pass


__all__ = ["InMemoryVectorStore", "cosine_similarity"]