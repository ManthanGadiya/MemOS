"""Tests for the persistent SQLite vector and graph stores.

Covers the storage contract from docs/Database.md and the transaction
before-image primitives (``vector_store.get``, ``graph_store.cache_node`` /
``get_node``) used by ``memos.kernel.transaction``:

- vectors upsert/get/delete/search/clear and survive a reopen,
- relationships persist across a reopen and support traverse/neighbors,
- the node cache round-trips a :class:`MemoryObject`,
- ``build_kernel`` selects the configured backend and rejects unsupported ones
  with a clear, actionable error.
"""

from __future__ import annotations

import pytest

from memos.config.settings import Settings
from memos.domain.memory import LifecycleState, MemoryObject, MemoryType, PermissionLevel
from memos.domain.relationship import Relationship, RelationshipType
from memos.kernel.factory import build_kernel
from memos.storage.protocols import GraphStore, VectorStore
from memos.storage.sqlite_graph import SQLiteGraphStore
from memos.storage.sqlite_vector import SQLiteVectorStore


# ----------------------------------------------------------------------
# Vector store
# ----------------------------------------------------------------------

def _make_vector_store(tmp_path) -> SQLiteVectorStore:
    return SQLiteVectorStore(tmp_path / "vectors.db")


def test_vector_upsert_get_delete(tmp_path):
    store: VectorStore = _make_vector_store(tmp_path)
    store.upsert("m1", [1.0, 0.0, 0.0], {"owner": "u"})
    assert store.get("m1") == ([1.0, 0.0, 0.0], {"owner": "u"})
    store.delete("m1")
    assert store.get("m1") is None


def test_vector_search_ranks_by_similarity(tmp_path):
    store: VectorStore = _make_vector_store(tmp_path)
    store.upsert("near", [1.0, 0.0, 0.0], {})
    store.upsert("far", [0.0, 1.0, 0.0], {})
    results = store.search([1.0, 0.0, 0.0], top_k=2)
    assert results[0][0] == "near"
    assert results[0][1] > results[1][1]


def test_vector_search_payload_filter(tmp_path):
    store: VectorStore = _make_vector_store(tmp_path)
    store.upsert("a", [1.0, 0.0], {"kind": "x"})
    store.upsert("b", [1.0, 0.0], {"kind": "y"})
    results = store.search([1.0, 0.0], top_k=10, filter_payload={"kind": "x"})
    assert [m for m, _ in results] == ["a"]


def test_vector_persists_across_reopen(tmp_path):
    path = tmp_path / "vectors.db"
    store = SQLiteVectorStore(path)
    store.upsert("m1", [0.5, 0.5], {"owner": "u"})
    store.close()

    reopened = SQLiteVectorStore(path)
    try:
        assert reopened.get("m1") == ([0.5, 0.5], {"owner": "u"})
    finally:
        reopened.close()


# ----------------------------------------------------------------------
# Graph store
# ----------------------------------------------------------------------

def _make_memory(memory_id: str) -> MemoryObject:
    return MemoryObject(
        memory_id=memory_id,
        content="payload",
        owner_id="u",
        type=MemoryType.SEMANTIC,
        permission=PermissionLevel.PRIVATE,
        state=LifecycleState.ACTIVE,
    )


def _make_graph_store(tmp_path) -> SQLiteGraphStore:
    return SQLiteGraphStore(tmp_path / "graph.db")


def test_graph_relationship_crud(tmp_path):
    store: GraphStore = _make_graph_store(tmp_path)
    rel = Relationship(
        source_id="a", target_id="b", type=RelationshipType.RELATED_TO, weight=2.0
    )
    store.upsert_relationship(rel)
    assert len(store.get_relationships(memory_id="a", direction="out")) == 1
    store.delete_relationship(rel.relationship_id)
    assert store.get_relationships(memory_id="a") == []


def test_graph_node_cache_round_trips(tmp_path):
    store: GraphStore = _make_graph_store(tmp_path)
    mem = _make_memory("a")
    store.cache_node(mem)
    restored = store.get_node("a")
    assert restored is not None
    assert restored.memory_id == "a"
    assert restored.type is MemoryType.SEMANTIC


def test_graph_traverse_and_neighbors(tmp_path):
    store: GraphStore = _make_graph_store(tmp_path)
    store.cache_node(_make_memory("a"))
    store.cache_node(_make_memory("b"))
    store.upsert_relationship(
        Relationship(source_id="a", target_id="b", type=RelationshipType.RELATED_TO)
    )
    edges = store.traverse("a", max_depth=2)
    assert len(edges) == 1
    neighbors = store.neighbors("a")
    assert [m.memory_id for m in neighbors] == ["b"]


def test_graph_delete_node_purges_edges(tmp_path):
    store: GraphStore = _make_graph_store(tmp_path)
    rel = Relationship(source_id="a", target_id="b", type=RelationshipType.RELATED_TO)
    store.upsert_relationship(rel)
    store.delete_node("a")
    assert store.get_relationships(memory_id="a") == []
    assert store.get_relationships(memory_id="b") == []


def test_graph_persists_across_reopen(tmp_path):
    path = tmp_path / "graph.db"
    store = SQLiteGraphStore(path)
    store.cache_node(_make_memory("a"))
    store.upsert_relationship(
        Relationship(source_id="a", target_id="b", type=RelationshipType.RELATED_TO)
    )
    store.close()

    reopened = SQLiteGraphStore(path)
    try:
        assert reopened.get_node("a") is not None
        assert len(reopened.get_relationships(memory_id="a", direction="out")) == 1
    finally:
        reopened.close()


# ----------------------------------------------------------------------
# Factory backend selection
# ----------------------------------------------------------------------

def test_build_kernel_default_uses_sqlite_stores(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "meta.db"),
        vector_db_path=str(tmp_path / "vec.db"),
        graph_db_path=str(tmp_path / "graph.db"),
        vector_store_backend="sqlite",
        graph_store_backend="sqlite",
    )
    kernel = build_kernel(settings)
    try:
        assert isinstance(kernel._vector_store, SQLiteVectorStore)
        assert isinstance(kernel._graph_store, SQLiteGraphStore)
    finally:
        kernel.close()


def test_build_kernel_rejects_unsupported_vector_backend(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "meta.db"),
        vector_store_backend="qdrant",
    )
    with pytest.raises(ValueError, match="unsupported vector_store_backend"):
        build_kernel(settings)


def test_build_kernel_rejects_unsupported_graph_backend(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "meta.db"),
        graph_store_backend="neo4j",
    )
    with pytest.raises(ValueError, match="unsupported graph_store_backend"):
        build_kernel(settings)


__all__ = [
    "test_vector_upsert_get_delete",
    "test_vector_search_ranks_by_similarity",
    "test_vector_search_payload_filter",
    "test_vector_persists_across_reopen",
    "test_graph_relationship_crud",
    "test_graph_node_cache_round_trips",
    "test_graph_traverse_and_neighbors",
    "test_graph_delete_node_purges_edges",
    "test_graph_persists_across_reopen",
    "test_build_kernel_default_uses_sqlite_stores",
    "test_build_kernel_rejects_unsupported_vector_backend",
    "test_build_kernel_rejects_unsupported_graph_backend",
]
