"""Embedding package."""

from .hash_embedder import HashEmbedder
from .protocol import EmbeddingProvider

__all__ = ["EmbeddingProvider", "HashEmbedder"]