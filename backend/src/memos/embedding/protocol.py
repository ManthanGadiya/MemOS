"""Embedding interface for MemOS.

The embedding provider is an injected dependency of the Memory Kernel. In
development we use a deterministic local embedder (see
:mod:`memos.embedding.hash_embedder`) so the system is fully functional
without external API keys; a production provider (e.g. an embedding model
server) implements the same protocol.
"""

from __future__ import annotations

from typing import List, Protocol


class EmbeddingProvider(Protocol):
    """Converts text into a dense vector."""

    dimension: int

    def embed(self, text: str) -> List[float]: ...

    def embed_batch(self, texts: List[str]) -> List[List[float]]: ...
