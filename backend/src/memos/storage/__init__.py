"""Storage package: protocol definitions and default adapters."""

from .in_memory_graph import InMemoryGraphStore
from .in_memory_vector import InMemoryVectorStore, cosine_similarity
from .protocols import (
    GraphStore,
    MetadataStore,
    StorageBackend,
    VectorStore,
)
from .sqlite_graph import SQLiteGraphStore
from .sqlite_metadata import SQLiteMetadataStore
from .sqlite_vector import SQLiteVectorStore

__all__ = [
    "GraphStore",
    "InMemoryGraphStore",
    "InMemoryVectorStore",
    "MetadataStore",
    "SQLiteGraphStore",
    "SQLiteMetadataStore",
    "SQLiteVectorStore",
    "StorageBackend",
    "VectorStore",
    "cosine_similarity",
]