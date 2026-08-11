"""Storage abstraction for MemOS.

The storage layer is split into three backends with narrow interfaces:

- :class:`MetadataStore` — relational metadata (SQLite in dev, PostgreSQL in prod)
- :class:`VectorStore` — dense-vector similarity search (Qdrant in prod, in-memory in dev)
- :class:`GraphStore` — typed relationship graph (Neo4j in prod, in-memory in dev)

The Memory Kernel depends only on these protocols; it never touches a
concrete driver. Adapters are injected via dependency injection.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

from memos.domain.memory import LifecycleState, MemoryObject, MemoryType
from memos.domain.relationship import Relationship


class MetadataStore(Protocol):
    """Relational metadata persistence for memory objects."""

    def create(self, obj: MemoryObject) -> MemoryObject: ...

    def get(self, memory_id: str) -> Optional[MemoryObject]: ...

    def update(self, obj: MemoryObject) -> MemoryObject: ...

    def delete(self, memory_id: str) -> None: ...

    def list(
        self,
        owner_id: Optional[str] = None,
        memory_type: Optional[MemoryType] = None,
        state: Optional[LifecycleState] = None,
        tags: Optional[List[str]] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[MemoryObject]: ...

    def count(self, owner_id: Optional[str] = None) -> int: ...

    def search_metadata(self, query: str, limit: int = 20) -> List[MemoryObject]: ...

    def search_tags(self, tags: List[str], limit: int = 20) -> List[MemoryObject]: ...

    def close(self) -> None: ...


class VectorStore(Protocol):
    """Dense-vector similarity search."""

    def upsert(self, memory_id: str, vector: List[float], payload: Dict[str, Any]) -> None: ...

    def delete(self, memory_id: str) -> None: ...

    def search(
        self,
        vector: List[float],
        top_k: int = 10,
        filter_payload: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[str, float]]: ...

    def clear(self) -> None: ...

    def close(self) -> None: ...


class GraphStore(Protocol):
    """Typed relationship graph."""

    def upsert_relationship(self, rel: Relationship) -> None: ...

    def delete_relationship(self, relationship_id: str) -> None: ...

    def delete_node(self, memory_id: str) -> None: ...

    def get_relationships(
        self,
        memory_id: Optional[str] = None,
        relationship_type: Optional[str] = None,
        direction: str = "any",
    ) -> List[Relationship]: ...

    def traverse(
        self,
        start_id: str,
        max_depth: int = 2,
        relationship_types: Optional[List[str]] = None,
    ) -> List[Tuple[Relationship, int]]: ...

    def neighbors(
        self, memory_id: str, relationship_types: Optional[List[str]] = None, depth: int = 1
    ) -> List[MemoryObject]: ...

    def clear(self) -> None: ...

    def close(self) -> None: ...


class StorageBackend(Protocol):
    """Facade exposing all three stores for a single storage configuration."""

    metadata: MetadataStore
    vector: VectorStore
    graph: GraphStore
    name: str

    def initialize(self) -> None: ...

    def close(self) -> None: ...
