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
        RelationshipType.FOLLOW_UP,
        weight=0.8,
        metadata={"provenance": "test"},
    )

    assert isinstance(relationship, Relationship)
    assert relationship.source_id == "source-1"
    assert relationship.target_id == "target-1"
    assert relationship.type == RelationshipType.FOLLOW_UP
    assert relationship.weight == 0.8
    assert relationship.metadata == {"provenance": "test"}
    assert relationship.relationship_id

    persisted = graph_store.get_relationships(direction="any")
    assert len(persisted) == 1
    assert persisted[0].relationship_id == relationship.relationship_id


def test_get_relationships_by_memory_and_direction(
    engine: GraphEngine,
) -> None:
    engine.add_relationship("x", "y", RelationshipType.RELATED_TO)
    engine.add_relationship("y", "x", RelationshipType.REFERENCES)
    engine.add_relationship("y", "z", RelationshipType.FOLLOW_UP)

    outgoing = engine.get_relationships(memory_id="y", direction="out")
    assert_ids(outgoing, ["y->x", "y->z"])

    incoming = engine.get_relationships(memory_id="y", direction="in")
    assert_ids(incoming, ["x->y"])

    any_direction = engine.get_relationships(memory_id="y", direction="any")
    assert len(any_direction) == 3


def test_get_relationships_by_type(engine: GraphEngine) -> None:
    engine.add_relationship("x", "y", RelationshipType.FOLLOW_UP)
    engine.add_relationship("x", "z", RelationshipType.REFERENCES)

    follow_ups = engine.get_relationships(relationship_type="follow_up")
    assert len(follow_ups) == 1
    assert follow_ups[0].target_id == "y"


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
    assert depths["b->c"] == 2
    # The CONTRADICTS self-loop a->a is not traversable by default.
    assert "a->a" not in depths
    assert "c->d" not in depths  # depth 3 exceeds the limit


def test_traverse_cycle_safety(chain_engine: GraphEngine) -> None:
    edges = chain_engine.traverse("a", max_depth=10)

    # Default traversal excludes CONTRADICTS, so the self-loop is absent and
    # the chain is visited exactly once without revisits or a hang.
    self_loops = [r for r, _ in edges if r.source_id == "a" and r.target_id == "a"]
    assert len(self_loops) == 0
    assert len(edges) == 3  # a->b, b->c, c->d
    assert all(depth <= 10 for _, depth in edges)


def test_traverse_explicit_contradicts_included(chain_engine: GraphEngine) -> None:
    # When CONTRADICTS is explicitly requested it is traversed.
    edges = chain_engine.traverse(
        "a", max_depth=1, relationship_types=["contradicts"]
    )
    self_loops = [r for r, _ in edges if r.source_id == "a" and r.target_id == "a"]
    assert len(self_loops) == 1


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


def test_traverse_default_excludes_contradicts(engine: GraphEngine) -> None:
    engine.add_relationship("n", "p", RelationshipType.RELATED_TO)
    engine.add_relationship("n", "q", RelationshipType.CONTRADICTS)

    default_edges = engine.traverse("n", max_depth=1)
    assert len(default_edges) == 1
    assert default_edges[0][0].target_id == "p"

    explicit_edges = engine.traverse(
        "n", max_depth=1, relationship_types=["contradicts"]
    )
    assert len(explicit_edges) == 1
    assert explicit_edges[0][0].target_id == "q"


def test_traverse_graph_min_weight(engine: GraphEngine) -> None:
    engine.add_relationship("n", "p", RelationshipType.RELATED_TO, weight=0.8)
    engine.add_relationship("n", "q", RelationshipType.RELATED_TO, weight=0.3)

    filtered = engine.traverse("n", max_depth=1, graph_min_weight=0.5)
    assert len(filtered) == 1
    assert filtered[0][0].target_id == "p"


def test_traverse_max_nodes_cap(engine: GraphEngine) -> None:
    engine.add_relationship("a", "b", RelationshipType.RELATED_TO)
    engine.add_relationship("b", "c", RelationshipType.RELATED_TO)
    engine.add_relationship("c", "d", RelationshipType.RELATED_TO)

    edges = engine.traverse("a", max_depth=10, max_nodes=2)

    sources = {r.source_id for r, _ in edges}
    # Expansion is capped at 2 nodes (a and b), so "c" is never expanded.
    assert "c" not in sources
    assert "c->d" not in [f"{r.source_id}->{r.target_id}" for r, _ in edges]
    assert "b->c" in [f"{r.source_id}->{r.target_id}" for r, _ in edges]


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


# ---- weight bounds ------------------------------------------------------------


def test_negative_weight_raises_validation_error(engine: GraphEngine) -> None:
    with pytest.raises(ValidationError):
        engine.add_relationship(
            "x", "y", RelationshipType.RELATED_TO, weight=-0.1
        )


def test_weight_above_one_raises_validation_error(engine: GraphEngine) -> None:
    with pytest.raises(ValidationError):
        engine.add_relationship(
            "x", "y", RelationshipType.RELATED_TO, weight=1.5
        )


def test_zero_weight_is_accepted(engine: GraphEngine) -> None:
    relationship = engine.add_relationship(
        "x", "y", RelationshipType.RELATED_TO, weight=0.0
    )
    assert relationship.weight == 0.0


def test_unit_weight_is_accepted(engine: GraphEngine) -> None:
    relationship = engine.add_relationship(
        "x", "y", RelationshipType.REFERENCES, weight=1.0
    )
    assert relationship.weight == 1.0


def test_missing_relationship_type_raises_validation_error(
    engine: GraphEngine,
) -> None:
    with pytest.raises(ValidationError):
        engine.add_relationship("x", "y", None)


# ---- cycle prevention -----------------------------------------------------------


def test_parent_of_self_loop_rejected(engine: GraphEngine) -> None:
    with pytest.raises(ValidationError):
        engine.add_relationship("p", "p", RelationshipType.PARENT_OF)


def test_child_of_self_loop_rejected(engine: GraphEngine) -> None:
    with pytest.raises(ValidationError):
        engine.add_relationship("c", "c", RelationshipType.CHILD_OF)


def test_parent_of_cycle_rejected(engine: GraphEngine) -> None:
    engine.add_relationship("a", "b", RelationshipType.PARENT_OF)
    # Adding b -> a would close the cycle a -> b -> a and must be rejected.
    with pytest.raises(ValidationError):
        engine.add_relationship("b", "a", RelationshipType.PARENT_OF)


def test_child_of_cycle_rejected(engine: GraphEngine) -> None:
    engine.add_relationship("a", "b", RelationshipType.CHILD_OF)
    with pytest.raises(ValidationError):
        engine.add_relationship("b", "a", RelationshipType.CHILD_OF)


def test_related_to_cycle_allowed(engine: GraphEngine) -> None:
    first = engine.add_relationship("x", "y", RelationshipType.RELATED_TO)
    second = engine.add_relationship("y", "x", RelationshipType.RELATED_TO)
    assert first.source_id == "x" and first.target_id == "y"
    assert second.source_id == "y" and second.target_id == "x"


def test_self_loop_is_allowed_for_cycle_permitting_type(
    engine: GraphEngine,
) -> None:
    relationship = engine.add_relationship(
        "x", "x", RelationshipType.CONTRADICTS
    )
    assert relationship.source_id == "x"
    assert relationship.target_id == "x"


# ---- node lifecycle validation --------------------------------------------------


def test_node_validator_rejects_missing_memory(
    engine: GraphEngine, graph_store: InMemoryGraphStore
) -> None:
    active_ids = {"existing-node"}
    validating_engine = GraphEngine(
        graph_store, node_validator=lambda mid: mid in active_ids
    )

    # Both endpoints must exist; a missing endpoint is rejected.
    with pytest.raises(ValidationError):
        validating_engine.add_relationship(
            "existing-node", "missing-node", RelationshipType.RELATED_TO
        )
    with pytest.raises(ValidationError):
        validating_engine.add_relationship(
            "missing-node", "existing-node", RelationshipType.RELATED_TO
        )


def test_node_validator_accepts_active_memory(
    engine: GraphEngine, graph_store: InMemoryGraphStore
) -> None:
    active_ids = {"existing-node"}
    validating_engine = GraphEngine(
        graph_store, node_validator=lambda mid: mid in active_ids
    )
    relationship = validating_engine.add_relationship(
        "existing-node", "existing-node", RelationshipType.REFERENCES
    )
    assert relationship.source_id == "existing-node"


def test_no_node_validator_skips_check(engine: GraphEngine) -> None:
    # Without an injected validator, arbitrary IDs are accepted (dev/standalone).
    relationship = engine.add_relationship(
        "unknown-source", "unknown-target", RelationshipType.RELATED_TO
    )
    assert relationship.source_id == "unknown-source"