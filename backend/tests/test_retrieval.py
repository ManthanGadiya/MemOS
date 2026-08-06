"""Tests for the MemOS Retrieval Engine.

Covers the deterministic hybrid retrieval pipeline from docs/Algorithms.md:
- hybrid ranking (scores in [0, 1], descending order, deterministic)
- pure semantic, metadata keyword, tag, and graph-depth retrieval modes
- permission filtering (PRIVATE memories hidden from non-owners)
- post-filters (owner / type / state / tags) and the documented default
  lifecycle state of ACTIVE
- input validation and top_k defaulting
"""

from __future__ import annotations

from typing import List, Set

import pytest

from memos.config.settings import Settings
from memos.domain.exceptions import ValidationError
from memos.domain.memory import (
    LifecycleState,
    MemoryObject,
    MemoryType,
    PermissionLevel,
    RelationshipType,
)
from memos.embedding.hash_embedder import HashEmbedder
from memos.engines import RetrievalEngine, ScoredMemory
from memos.engines.graph import GraphEngine
from memos.engines.permission import PermissionEngine
from memos.storage.in_memory_graph import InMemoryGraphStore
from memos.storage.in_memory_vector import InMemoryVectorStore
from memos.storage.sqlite_metadata import SQLiteMetadataStore


class RetrievalHarness:
    """Wires a RetrievalEngine with fresh stores and a seeding helper."""

    def __init__(
        self,
        engine: RetrievalEngine,
        metadata_store: SQLiteMetadataStore,
        vector_store: InMemoryVectorStore,
        graph_store: InMemoryGraphStore,
        graph_engine: GraphEngine,
        embedder: HashEmbedder,
        settings: Settings,
    ) -> None:
        self.engine = engine
        self.metadata_store = metadata_store
        self.vector_store = vector_store
        self.graph_store = graph_store
        self.graph_engine = graph_engine
        self.embedder = embedder
        self.settings = settings

    def add(self, memory: MemoryObject) -> MemoryObject:
        """Persist a memory to all three stores (metadata, vector, graph)."""
        self.metadata_store.create(memory)
        self.vector_store.upsert(
            memory.memory_id, self.embedder.embed(memory.content), {}
        )
        self.graph_store.cache_node(memory)
        return memory


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def harness(tmp_path, settings: Settings) -> RetrievalHarness:
    """A fresh engine wired to fresh SQLite / in-memory stores per test."""
    metadata_store = SQLiteMetadataStore(tmp_path / "retrieval_test.db")
    vector_store = InMemoryVectorStore()
    graph_store = InMemoryGraphStore()
    embedder = HashEmbedder(dimension=64)
    graph_engine = GraphEngine(graph_store)
    permission_engine = PermissionEngine(settings)
    engine = RetrievalEngine(
        metadata_store=metadata_store,
        vector_store=vector_store,
        graph_engine=graph_engine,
        embedder=embedder,
        permission_engine=permission_engine,
        settings=settings,
    )
    try:
        yield RetrievalHarness(
            engine,
            metadata_store,
            vector_store,
            graph_store,
            graph_engine,
            embedder,
            settings,
        )
    finally:
        metadata_store.close()


def result_ids(results: List[ScoredMemory]) -> List[str]:
    """The ordered memory IDs of a retrieval result."""
    return [item.memory.memory_id for item in results]


def seed(harness: RetrievalHarness, content: str, **kwargs) -> MemoryObject:
    """Construct, persist, and index a memory; return it."""
    return harness.add(MemoryObject(content=content, **kwargs))


# ----------------------------------------------------------------------
# hybrid_search
# ----------------------------------------------------------------------


def test_hybrid_search_returns_scores_in_unit_range_and_desc_order(
    harness: RetrievalHarness,
) -> None:
    fox = seed(harness, "quick brown fox jumps over the lazy dog")
    seed(harness, "slow green turtle walks across the sand")
    seed(harness, "the stock market rallied sharply today")

    results = harness.engine.hybrid_search("quick brown fox")

    assert results, "hybrid search should return at least one candidate"
    assert result_ids(results)[0] == fox.memory_id
    for item in results:
        assert isinstance(item, ScoredMemory)
        assert 0.0 <= item.score <= 1.0
    assert [item.score for item in results] == sorted(
        (item.score for item in results), reverse=True
    ), "scores must be ordered descending"


def test_hybrid_search_is_deterministic(harness: RetrievalHarness) -> None:
    seed(harness, "quick brown fox jumps over the lazy dog")
    seed(harness, "slow green turtle walks across the sand")
    seed(harness, "the stock market rallied sharply today")

    first = result_ids(harness.engine.hybrid_search("quick brown fox"))
    second = result_ids(harness.engine.hybrid_search("quick brown fox"))

    assert first == second


def test_hybrid_search_includes_metadata_only_candidate_with_zero_similarity(
    harness: RetrievalHarness,
) -> None:
    memory = MemoryObject(content="unique zebra note about migrations")
    # Only the metadata store knows this memory: no embedding was indexed.
    harness.metadata_store.create(memory)

    results = harness.engine.hybrid_search("zebra")

    assert result_ids(results) == [memory.memory_id]
    assert results[0].similarity == 0.0


def test_hybrid_search_default_state_excludes_archived_and_deleted(
    harness: RetrievalHarness,
) -> None:
    """docs/Algorithms.md 5.2 pins the default lifecycle state to ACTIVE."""
    active = seed(harness, "stateful data record", state=LifecycleState.ACTIVE)
    seed(harness, "stateful data record", state=LifecycleState.ARCHIVED)
    seed(harness, "stateful data record", state=LifecycleState.DELETED)

    default_results = harness.engine.hybrid_search("stateful")
    assert result_ids(default_results) == [active.memory_id]

    archived = harness.engine.hybrid_search("stateful", state=LifecycleState.ARCHIVED)
    assert len(archived) == 1
    assert archived[0].memory.state is LifecycleState.ARCHIVED

    deleted = harness.engine.hybrid_search("stateful", state=LifecycleState.DELETED)
    assert len(deleted) == 1
    assert deleted[0].memory.state is LifecycleState.DELETED


def test_hybrid_search_filters_by_owner(harness: RetrievalHarness) -> None:
    alice = seed(harness, "shared project alpha data", owner_id="alice")
    seed(harness, "shared project beta data", owner_id="bob")

    results = harness.engine.hybrid_search("project", owner_id="alice")

    assert result_ids(results) == [alice.memory_id]


def test_hybrid_search_filters_by_memory_type(harness: RetrievalHarness) -> None:
    fact = seed(harness, "daily observation log", type=MemoryType.FACT)
    seed(harness, "daily observation log", type=MemoryType.EPISODIC)

    results = harness.engine.hybrid_search("observation", memory_type=MemoryType.FACT)

    assert result_ids(results) == [fact.memory_id]


def test_hybrid_search_filters_by_tags(harness: RetrievalHarness) -> None:
    urgent = seed(harness, "tagged reminder item", tags=["urgent", "work"])
    seed(harness, "tagged reminder item", tags=["personal"])

    results = harness.engine.hybrid_search("reminder", tags=["urgent"])

    assert result_ids(results) == [urgent.memory_id]


def test_hybrid_search_permission_filter_hides_private_of_other_principal(
    harness: RetrievalHarness,
) -> None:
    alice = seed(
        harness,
        "alice secret memory plans",
        owner_id="alice",
        permission=PermissionLevel.PRIVATE,
    )
    bob = seed(
        harness,
        "bob public memory notes",
        owner_id="bob",
        permission=PermissionLevel.PRIVATE,
    )
    system = seed(
        harness,
        "system kernel memory state",
        owner_id="system",
        permission=PermissionLevel.SYSTEM,
    )

    results = harness.engine.hybrid_search("memory", principal_id="bob")

    returned: Set[str] = set(result_ids(results))
    assert alice.memory_id not in returned, "non-owner must not see PRIVATE memory"
    assert bob.memory_id in returned
    assert system.memory_id in returned

    all_results = harness.engine.hybrid_search("memory")
    assert alice.memory_id in set(result_ids(all_results)), (
        "system principal bypasses permissions"
    )


def test_hybrid_search_respects_top_k_parameter(harness: RetrievalHarness) -> None:
    for index in range(5):
        seed(harness, f"echo memory number {index}")

    results = harness.engine.hybrid_search("echo", top_k=2)

    assert len(results) == 2


def test_hybrid_search_uses_default_top_k_when_none(harness: RetrievalHarness) -> None:
    for index in range(12):
        seed(harness, f"echo memory number {index}")

    results = harness.engine.hybrid_search("echo")

    assert len(results) == harness.settings.default_top_k


def test_hybrid_search_empty_query_raises_validation_error(
    harness: RetrievalHarness,
) -> None:
    with pytest.raises(ValidationError):
        harness.engine.hybrid_search("   ")


# ----------------------------------------------------------------------
# semantic_search
# ----------------------------------------------------------------------


def test_semantic_search_returns_vector_ranked_results(
    harness: RetrievalHarness,
) -> None:
    top = seed(harness, "quick brown fox jumps over the lazy dog")
    seed(harness, "slow green turtle walks across the sand")
    seed(harness, "the stock market rallied sharply today")

    results = harness.engine.semantic_search("quick brown fox")

    assert result_ids(results)[0] == top.memory_id
    assert all(0.0 <= item.score <= 1.0 for item in results)
    assert [item.score for item in results] == sorted(
        (item.score for item in results), reverse=True
    )


def test_semantic_search_empty_query_raises_validation_error(
    harness: RetrievalHarness,
) -> None:
    with pytest.raises(ValidationError):
        harness.engine.semantic_search("")


# ----------------------------------------------------------------------
# metadata_search
# ----------------------------------------------------------------------


def test_metadata_search_finds_substring_matches(harness: RetrievalHarness) -> None:
    target = seed(harness, "the quick brown fox jumped the fence")
    seed(harness, "the stock market opened higher today")

    results = harness.engine.metadata_search("brown")

    assert result_ids(results) == [target.memory_id]
    assert all(item.similarity == 0.0 for item in results)


def test_metadata_search_empty_query_raises_validation_error(
    harness: RetrievalHarness,
) -> None:
    with pytest.raises(ValidationError):
        harness.engine.metadata_search("")


# ----------------------------------------------------------------------
# tag_search
# ----------------------------------------------------------------------


def test_tag_search_matches_requested_tags(harness: RetrievalHarness) -> None:
    nature = seed(harness, "fox den observation", tags=["nature", "fox"])
    seed(harness, "quarterly earnings call", tags=["finance"])

    results = harness.engine.tag_search(["nature"])

    assert result_ids(results) == [nature.memory_id]


def test_tag_search_scores_by_overlap(harness: RetrievalHarness) -> None:
    seed(harness, "experiment results", tags=["science"])
    seed(harness, "stargazing notes", tags=["science"])

    results = harness.engine.tag_search(["science", "space"])

    # Both memories match one of two requested tags -> equal overlap 0.5.
    assert len(results) == 2
    assert all(item.score == 0.5 for item in results)


def test_tag_search_empty_tags_raise_validation_error(
    harness: RetrievalHarness,
) -> None:
    with pytest.raises(ValidationError):
        harness.engine.tag_search([])


# ----------------------------------------------------------------------
# graph_search
# ----------------------------------------------------------------------


def test_graph_search_orders_by_depth(harness: RetrievalHarness) -> None:
    for memory_id, content in [
        ("a", "node a"),
        ("b", "node b"),
        ("c", "node c"),
        ("d", "node d"),
    ]:
        seed(harness, content, memory_id=memory_id)
    harness.graph_engine.add_relationship("a", "b", RelationshipType.RELATED_TO)
    harness.graph_engine.add_relationship("b", "c", RelationshipType.DEPENDS_ON)
    harness.graph_engine.add_relationship("c", "d", RelationshipType.REFERENCES)

    results = harness.engine.graph_search("a", max_depth=2)

    # a -> b (depth 1, score 1/2) and b -> c (depth 2, score 1/3).
    assert result_ids(results) == ["b", "c"]
    assert results[0].score > results[1].score


def test_graph_search_respects_max_depth(harness: RetrievalHarness) -> None:
    seed(harness, "node a", memory_id="a")
    seed(harness, "node b", memory_id="b")
    seed(harness, "node c", memory_id="c")
    harness.graph_engine.add_relationship("a", "b", RelationshipType.RELATED_TO)
    harness.graph_engine.add_relationship("b", "c", RelationshipType.DEPENDS_ON)

    results = harness.engine.graph_search("a", max_depth=1)

    assert result_ids(results) == ["b"]


def test_graph_search_isolated_start_returns_nothing(
    harness: RetrievalHarness,
) -> None:
    seed(harness, "lonely node", memory_id="isolated")

    results = harness.engine.graph_search("isolated")

    assert results == []
