"""Graph Engine for MemOS.

The Graph Engine manages relationships among :class:`MemoryObject` entities
and provides graph algorithms on top of the injected :class:`GraphStore`.

Design rules enforced here:

- All persistence goes through the injected ``graph_store`` (dependency
  injection). The engine never imports a concrete adapter, so the Memory
  Kernel can swap SQLite/Neo4j/in-memory backends without touching this
  module.
- The engine owns validation, traversal safety, and shortest-path logic;
  the store owns physical persistence.
- Relationship weight is bounded: ``0 <= weight <= 1`` (AL-003).
- Cycles are rejected at creation time unless the relationship type
  explicitly permits them (Algorithms §8.4). ``PARENT_OF`` and
  ``CHILD_OF`` reject cycles; every other type permits them.
- Self-loops follow the same cycle rule: a self-loop is always a cycle,
  so it is rejected for ``PARENT_OF``/``CHILD_OF`` and allowed for the
  remaining types (a memory may legitimately contradict itself across
  versions, so a self-referential ``CONTRADICTS`` edge is meaningful).
- Default traversal follows the documented traversable types
  (Algorithms §5.4): ``RELATED_TO``, ``DEPENDS_ON``, ``REFERENCES``,
  ``FOLLOW_UP``, ``SUPERSEDES``. ``CONTRADICTS`` is a negative signal and
  is excluded from default traversal.
- Traversal and path discovery are breadth-first and track visited nodes
  so cycles cannot cause infinite loops, and stop expanding once
  ``max_nodes`` (default 50) is reached (Algorithms §8.2).
"""

from __future__ import annotations

from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from memos.domain.exceptions import NotFoundError, ValidationError
from memos.domain.memory import MemoryObject, RelationshipType
from memos.domain.relationship import Relationship
from memos.storage.protocols import GraphStore


# Relationship types that permit circular edges (Algorithms §8.4). Every
# type other than PARENT_OF / CHILD_OF explicitly permits cycles.
CYCLE_PERMITTING_TYPES: frozenset[RelationshipType] = frozenset(
    {
        RelationshipType.RELATED_TO,
        RelationshipType.BELONGS_TO,
        RelationshipType.DEPENDS_ON,
        RelationshipType.SUPERSEDES,
        RelationshipType.CONTRADICTS,
        RelationshipType.REFERENCES,
        RelationshipType.FOLLOW_UP,
    }
)

# Relationship types that reject cycles at creation time (Algorithms §8.4).
CYCLE_REJECTING_TYPES: frozenset[RelationshipType] = frozenset(
    {
        RelationshipType.PARENT_OF,
        RelationshipType.CHILD_OF,
    }
)

# Relationship types used by default traversal (Algorithms §5.4).
# CONTRADICTS is a negative signal, not a traversal edge, and is therefore
# intentionally excluded from the default traversable set.
TRAVERSABLE_RELATIONSHIP_TYPES: frozenset[RelationshipType] = frozenset(
    {
        RelationshipType.RELATED_TO,
        RelationshipType.DEPENDS_ON,
        RelationshipType.REFERENCES,
        RelationshipType.FOLLOW_UP,
        RelationshipType.SUPERSEDES,
    }
)


class GraphEngine:
    """Validates and persists typed relationships, and runs graph queries.

    The engine is stateless between calls: all persistent state lives in the
    injected ``graph_store``. This keeps the engine independently testable
    and storage-agnostic.

    Args:
        graph_store: Backend that owns physical edge persistence.
        node_validator: Optional callable returning ``True`` when a memory
            ID exists and is active. When provided, ``add_relationship``
            rejects edges referencing missing or inactive memories
            (FR-030 / LC-007 / SRS §15). When ``None`` (standalone/dev
            use), node existence is not checked — the engine never imports
            the metadata store.
    """

    def __init__(
        self,
        graph_store: GraphStore,
        node_validator: Callable[[str], bool] | None = None,
    ) -> None:
        self._graph_store: GraphStore = graph_store
        self._node_validator: Callable[[str], bool] | None = node_validator

    # ---- relationship lifecycle -----------------------------------------

    def add_relationship(
        self,
        source_id: str,
        target_id: str,
        relationship_type: RelationshipType,
        weight: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Relationship:
        """Create and persist a relationship between two memories.

        Validation rules:
        - ``relationship_type`` must be a :class:`RelationshipType`
          (``None`` is rejected — every edge needs a semantic type).
        - ``weight`` must be in ``[0, 1]`` (AL-003; a negative or
          greater-than-one weight is meaningless as a signal strength).
        - If a ``node_validator`` was injected, both ``source_id`` and
          ``target_id`` must reference existing, active memories
          (FR-030 / LC-007 / SRS §15).
        - Cycle-rejecting types (``PARENT_OF`` / ``CHILD_OF``) reject any
          edge that would create a cycle, including self-loops
          (Algorithms §8.4). Other types permit cycles and self-loops.

        Args:
            source_id: Memory ID of the relationship source.
            target_id: Memory ID of the relationship target.
            relationship_type: Semantic type of the edge.
            weight: Edge weight in ``[0, 1]`` (default ``1.0``).
            metadata: Optional application metadata attached to the edge.

        Returns:
            The persisted :class:`Relationship` (with assigned
            ``relationship_id`` and ``created_at``).

        Raises:
            ValidationError: if ``relationship_type`` is ``None``,
                ``weight`` is outside ``[0, 1]``, a referenced memory is
                missing/inactive, or the edge would create a cycle for a
                cycle-rejecting type.
        """
        if relationship_type is None:
            raise ValidationError(
                "relationship_type is required; every edge needs a semantic type"
            )
        if not 0.0 <= weight <= 1.0:
            raise ValidationError(
                f"relationship weight must be in [0, 1], got {weight}"
            )
        if self._node_validator is not None and not (
            self._node_validator(source_id) and self._node_validator(target_id)
        ):
            raise ValidationError(
                "referenced memory does not exist or is not active"
            )
        if relationship_type in CYCLE_REJECTING_TYPES:
            if source_id == target_id:
                raise ValidationError(
                    "a self-loop is always a cycle and is not permitted "
                    f"for {relationship_type.value}"
                )
            if self._path_between(target_id, source_id):
                raise ValidationError(
                    f"adding {relationship_type.value} edge "
                    f"{source_id}->{target_id} would create a cycle"
                )

        relationship = Relationship(
            source_id=source_id,
            target_id=target_id,
            type=relationship_type,
            weight=weight,
            metadata=metadata if metadata is not None else {},
        )
        self._graph_store.upsert_relationship(relationship)
        return relationship

    def remove_relationship(self, relationship_id: str) -> None:
        """Remove a relationship by its identifier.

        Removal is idempotent: deleting a relationship that does not exist
        is a no-op at the store level.

        Args:
            relationship_id: Identifier of the relationship to remove.
        """
        self._graph_store.delete_relationship(relationship_id)

    def get_relationships(
        self,
        memory_id: Optional[str] = None,
        relationship_type: Optional[str] = None,
        direction: str = "any",
    ) -> List[Relationship]:
        """Query persisted relationships.

        Args:
            memory_id: If given, restrict to relationships touching this
                memory (direction-dependent).
            relationship_type: If given, restrict to this relationship
                type value (e.g. ``"related_to"``).
            direction: ``"out"``, ``"in"``, or ``"any"`` (default).

        Returns:
            Matching relationships sorted by creation time.
        """
        return self._graph_store.get_relationships(
            memory_id=memory_id,
            relationship_type=relationship_type,
            direction=direction,
        )

    # ---- graph algorithms -------------------------------------------------

    def traverse(
        self,
        start_id: str,
        max_depth: int = 2,
        relationship_types: Optional[List[str]] = None,
        graph_min_weight: float = 0.0,
        max_nodes: int = 50,
    ) -> List[Tuple[Relationship, int]]:
        """Breadth-first traversal from ``start_id`` over out-edges.

        Returns ``(edge, depth)`` pairs where ``depth`` is the number of
        hops from ``start_id`` to the edge's source. Visited nodes are
        tracked so cycles terminate, and expansion stops once ``max_nodes``
        nodes have been reached (Algorithms §8.2).

        When ``relationship_types`` is ``None`` the traversal defaults to
        :data:`TRAVERSABLE_RELATIONSHIP_TYPES` (Algorithms §5.4);
        ``CONTRADICTS`` is a negative signal and is excluded from default
        traversal. Edges with ``weight < graph_min_weight`` are filtered
        out (Algorithms §5.4).

        Args:
            start_id: Memory ID where traversal begins.
            max_depth: Maximum number of hops (default ``2``).
            relationship_types: Optional filter on relationship type
                values. Defaults to the traversable types when ``None``.
            graph_min_weight: Only traverse edges with
                ``weight >= graph_min_weight`` (default ``0.0``).
            max_nodes: Stop expanding once this many nodes have been
                reached (default ``50``).

        Returns:
            List of ``(relationship, depth)`` tuples in BFS order.
        """
        if relationship_types is None:
            relationship_types = [
                t.value for t in TRAVERSABLE_RELATIONSHIP_TYPES
            ]
        visited: set[str] = {start_id}
        frontier: Deque[Tuple[str, int]] = deque([(start_id, 0)])
        output: List[Tuple[Relationship, int]] = []

        while frontier:
            node_id, depth = frontier.popleft()
            if depth >= max_depth:
                continue
            for relationship in self._graph_store.get_relationships(
                memory_id=node_id, direction="out"
            ):
                if relationship.type.value not in relationship_types:
                    continue
                if relationship.weight < graph_min_weight:
                    continue
                output.append((relationship, depth + 1))
                if len(visited) >= max_nodes:
                    continue
                if relationship.target_id not in visited:
                    visited.add(relationship.target_id)
                    frontier.append((relationship.target_id, depth + 1))

        return output

    def neighbors(
        self,
        memory_id: str,
        relationship_types: Optional[List[str]] = None,
        depth: int = 1,
    ) -> List[MemoryObject]:
        """Return neighbor memory objects of ``memory_id``.

        Delegates to the store's ``neighbors`` so the adapter controls how
        node objects are resolved and cached.

        Args:
            memory_id: Memory ID whose neighborhood is requested.
            relationship_types: Optional filter on relationship types.
            depth: How many hops to expand (default ``1``).

        Returns:
            The neighbor :class:`MemoryObject` instances.
        """
        return self._graph_store.neighbors(
            memory_id=memory_id,
            relationship_types=relationship_types,
            depth=depth,
        )

    def degree(self, memory_id: str) -> int:
        """Count relationships touching ``memory_id`` (either direction).

        Used by the Retrieval Engine as a graph-density signal for
        importance and ranking.

        Args:
            memory_id: Memory ID whose degree is requested.

        Returns:
            Number of incident relationships.
        """
        return len(
            self._graph_store.get_relationships(
                memory_id=memory_id, direction="any"
            )
        )

    def shortest_path(self, start_id: str, target_id: str) -> List[str]:
        """Shortest path (by relationship count) between two memories.

        Breadth-first search over out-edges. The path is the ordered list
        of memory IDs from ``start_id`` to ``target_id`` inclusive.

        Args:
            start_id: Memory ID where the path begins.
            target_id: Memory ID where the path ends.

        Returns:
            List of memory IDs forming the shortest path. ``[start_id]``
            when ``start_id == target_id``.

        Raises:
            NotFoundError: if ``target_id`` is unreachable from
                ``start_id`` over out-edges.
        """
        if start_id == target_id:
            return [start_id]

        visited: set[str] = {start_id}
        frontier: Deque[Tuple[str, List[str]]] = deque([(start_id, [start_id])])

        while frontier:
            node_id, path = frontier.popleft()
            for relationship in self._graph_store.get_relationships(
                memory_id=node_id, direction="out"
            ):
                neighbor_id = relationship.target_id
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)
                next_path: List[str] = path + [neighbor_id]
                if neighbor_id == target_id:
                    return next_path
                frontier.append((neighbor_id, next_path))

        raise NotFoundError(
            f"no path from {start_id} to {target_id} in the memory graph"
        )

    # ---- internal helpers ------------------------------------------------

    def _path_between(self, start_id: str, target_id: str) -> bool:
        """Return ``True`` when a path of one or more edges connects the
        two memory IDs over out-edges (any relationship type).

        Used for cycle prevention (Algorithms §8.4): adding an edge
        ``source -> target`` creates a cycle exactly when a path already
        exists from ``target`` back to ``source``. A self-loop
        (``start_id == target_id``) trivially satisfies the path condition
        and is handled by the caller with an explicit self-loop check.
        """
        if start_id == target_id:
            return True
        visited: set[str] = {start_id}
        frontier: Deque[str] = deque([start_id])
        while frontier:
            node_id = frontier.popleft()
            for relationship in self._graph_store.get_relationships(
                memory_id=node_id, direction="out"
            ):
                neighbor_id = relationship.target_id
                if neighbor_id == target_id:
                    return True
                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    frontier.append(neighbor_id)
        return False


__all__ = [
    "CYCLE_PERMITTING_TYPES",
    "CYCLE_REJECTING_TYPES",
    "TRAVERSABLE_RELATIONSHIP_TYPES",
    "GraphEngine",
]
