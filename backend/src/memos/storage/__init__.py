"""Storage package: protocol definitions and default adapters."""

from .in_memory_graph import InMemoryGraphStore
from .in_memory_vector import InMemoryVectorStore, cosine_similarity
from .protocols import (
    GraphStore,
    MetadataStore,
    StorageBackend,
    VectorStore,
)
from .sqlite_metadata import SQLiteMetadataStore

__all__ = [
    "GraphStore",
    "InMemoryGraphStore",
    "InMemoryVectorStore",
    "MetadataStore",
    "SQLiteMetadataStore",
    "StorageBackend",
    "VectorStore",
    "cosine_similarity",
]