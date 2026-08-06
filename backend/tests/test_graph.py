"""Tests for the MemOS Graph Engine."""

from __future__ import annotations

from typing import Dict, List

import pytest

from memos.domain.exceptions import NotFoundError, ValidationError
from memos.domain.memory import MemoryObject, RelationshipType
from memos.domain.relationship import Relationship
from memos.engines.graph import GraphEngine
from memos.storage.in_memory_graph import InMemoryGraphStore


@pytest.fixture
def graph_store() -> InMemoryGraphStore:
    """A fresh in-memory store per test."""
    return InMemoryGraphStore()


@pytest.fixture
def engine(graph_store: InMemoryGraphStore) -> GraphEngine:
    """A GraphEngine wired to an in-memory store."""
    return GraphEngine(graph_store)


def build_memory(memory_id: str) -> MemoryObject:
    """Construct a MemoryObject with a known identifier."""
    return MemoryObject(content=f"memory-{memory_id}", memory_id=memory_id)


def add_node(graph_store: InMemoryGraphStore, memory_id: str) -> None:
    """Cache a node in the store so neighbor queries can resolve it."""
    graph_store.cache_node(build_memory(memory_id))


@pytest.fixture
def chain_engine(graph_store: InMemoryGraphStore) -> GraphEngine:
    """Engine pre-populated with a chain and a self-loop:

    a -> b -> c -> d
    a -> a  (self-loop, CONTRADICTS)
    """
    engine_instance = GraphEngine(graph_store)
    for memory_id in ["a", "b", "c", "d"]:
        add_node(graph_store, memory_id)

    engine_instance.add_relationship("a", "b", RelationshipType.RELATED_TO)
    engine_instance.add_relationship("b", "c", RelationshipType.DEPENDS_ON)
    engine_instance.add_relationship("c", "d", RelationshipType.REFERENCES)
    engine_instance.add_relationship("a", "a", RelationshipType.CONTRADICTS)
    return engine_instance


def assert_ids(relationships: List[Relationship], expected: List[str]) -> None:
    """Assert relationships match expected '{source}->{target}' labels."""
    actual = sorted(f"{r.source_id}->{r.target_id}" for r in relationships)
    assert actual == sorted(expected)


# ---- add + get ------------------------------------------------------------


def test_add_relationship_returns_persisted_relationship(
    engine: GraphEngine, graph_store: InMemoryGraphStore
) -> None:
    relationship = engine.add_relationship(
        "source-1",
        "target-1",
        RelationshipType.CAUSES,
        weight=0.8,
        metadata={"provenance": "test"},
    )

    assert isinstance(relationship, Relationship)
    assert relationship.source_id == "source-1"
    assert relationship.target_id == "target-1"
    assert relationship.type == RelationshipType.CAUSES
    assert relationship.weight == 0.8
    assert relationship.metadata == {"provenance": "test"}
    assert relationship.relationship_id

    persisted = graph_store.get_relationships(direction="any")
    assert len(persisted) == 1
    assert persisted[0].relationship_id == relationship.relationship_id


def test_get_relationships_by_memory_and_direction(engine: GraphEngine) -> None:
    engine.add_relationship("x", "y", RelationshipType.RELATED_TO)
    engine.add_relationship("y", "x", RelationshipType.REFERENCES)
    engine.add_relationship("y", "z", RelationshipType.CAUSES)

    outgoing = engine.get_relationships(memory_id="y", direction="out")
    assert_ids(outgoing, ["y->x", "y->z"])

    incoming = engine.get_relationships(memory_id="y", direction="in")
    assert_ids(incoming, ["x->y"])

    any_direction = engine.get_relationships(memory_id="y", direction="any")
    assert len(any_direction) == 3


def test_get_relationships_by_type(engine: GraphEngine) -> None:
    engine.add_relationship("x", "y", RelationshipType.CAUSES)
    engine.add_relationship("x", "z", RelationshipType.REFERENCES)

    causes = engine.get_relationships(relationship_type="causes")
    assert len(causes) == 1
    assert causes[0].target_id == "y"


# ---- remove ----------------------------------------------------------------


def test_remove_relationship(engine: GraphEngine) -> None:
    relationship = engine.add_relationship(
        "x", "y", RelationshipType.RELATED_TO
    )

    engine.remove_relationship(relationship.relationship_id)

    assert engine.get_relationships(memory_id="x", direction="any") == []


def test_remove_relationship_is_idempotent(engine: GraphEngine) -> None:
    relationship = engine.add_relationship(
        "x", "y", RelationshipType.RELATED_TO
    )
    engine.remove_relationship(relationship.relationship_id)
    # Removing again must not raise.
    engine.remove_relationship(relationship.relationship_id)


# ---- traversal ---------------------------------------------------------------


def test_traverse_respects_depth_limit(chain_engine: GraphEngine) -> None:
    edges = chain_engine.traverse("a", max_depth=2)

    depths: Dict[str, int] = {
        f"{r.source_id}->{r.target_id}": depth for r, depth in edges
    }
    assert depths["a->b"] == 1
    assert depths["a->a"] == 1  # self-loop is an out-edge at depth 1
    assert depths["b->c"] == 2
    assert "c->d" not in depths  # depth 3 exceeds the limit


def test_traverse_cycle_safety(chain_engine: GraphEngine) -> None:
    edges = chain_engine.traverse("a", max_depth=10)

    # The self-loop a->a appears exactly once; the chain is visited once.
    self_loops = [r for r, _ in edges if r.source_id == "a" and r.target_id == "a"]
    assert len(self_loops) == 1
    assert len(edges) == 4  # a->b, a->a, b->c, c->d — no revisits, no hang
    assert all(depth <= 10 for _, depth in edges)


def test_traverse_type_filter(chain_engine: GraphEngine) -> None:
    # Only edges whose type matches the filter are traversed (and therefore
    # only their targets become reachable).
    edges = chain_engine.traverse(
        "b", max_depth=3, relationship_types=["depends_on"]
    )

    assert len(edges) == 1
    edge, depth = edges[0]
    assert edge.type.value == "depends_on"
    assert edge.source_id == "b"
    assert edge.target_id == "c"
    assert depth == 1


def test_traverse_type_filter_blocks_unreachable_nodes(
    chain_engine: GraphEngine,
) -> None:
    # "a" only has related_to/contradicts out-edges, so no depends_on edge
    # is ever traversed and the traversal is empty.
    edges = chain_engine.traverse(
        "a", max_depth=3, relationship_types=["depends_on"]
    )
    assert edges == []


# ---- neighbors ---------------------------------------------------------------


def test_neighbors_direct(chain_engine: GraphEngine) -> None:
    neighbors = chain_engine.neighbors("b")
    ids = {m.memory_id for m in neighbors}
    assert ids == {"c"}


def test_neighbors_at_depth(chain_engine: GraphEngine) -> None:
    neighbors = chain_engine.neighbors("a", depth=2)
    ids = {m.memory_id for m in neighbors}
    # b (hop 1) and c (hop 2); the self-loop contributes nothing new.
    assert ids == {"a", "b", "c"}


# ---- degree ------------------------------------------------------------------


def test_degree_counts_all_directions(chain_engine: GraphEngine) -> None:
    # a has out-edges a->b and a->a (self-loop), no in-edges.
    assert chain_engine.degree("a") == 2
    # b: in from a->b and out to b->c.
    assert chain_engine.degree("b") == 2
    # d: in only (c->d).
    assert chain_engine.degree("d") == 1


def test_degree_of_isolated_node_is_zero(engine: GraphEngine) -> None:
    assert engine.degree("isolated") == 0


# ---- shortest path ------------------------------------------------------------


def test_shortest_path_found(chain_engine: GraphEngine) -> None:
    path = chain_engine.shortest_path("a", "d")
    assert path == ["a", "b", "c", "d"]


def test_shortest_path_returns_direct_hop(chain_engine: GraphEngine) -> None:
    path = chain_engine.shortest_path("a", "b")
    assert path == ["a", "b"]


def test_shortest_path_same_node(chain_engine: GraphEngine) -> None:
    assert chain_engine.shortest_path("b", "b") == ["b"]


def test_shortest_path_not_found(chain_engine: GraphEngine) -> None:
    with pytest.raises(NotFoundError):
        chain_engine.shortest_path("d", "a")


# ---- validation ---------------------------------------------------------------


def test_negative_weight_raises_validation_error(engine: GraphEngine) -> None:
    with pytest.raises(ValidationError):
        engine.add_relationship(
            "x", "y", RelationshipType.RELATED_TO, weight=-0.1
        )


def test_zero_weight_is_accepted(engine: GraphEngine) -> None:
    relationship = engine.add_relationship(
        "x", "y", RelationshipType.RELATED_TO, weight=0.0
    )
    assert relationship.weight == 0.0


def test_missing_relationship_type_raises_validation_error(
    engine: GraphEngine,
) -> None:
    with pytest.raises(ValidationError):
        engine.add_relationship("x", "y", None)


def test_self_loop_is_allowed(engine: GraphEngine) -> None:
    relationship = engine.add_relationship(
        "x", "x", RelationshipType.CONTRADICTS
    )
    assert relationship.source_id == "x"
    assert relationship.target_id == "x"
