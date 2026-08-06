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
- Self-loops (``source_id == target_id``) are allowed: a memory may
  legitimately contradict itself across versions, so a self-referential
  ``CONTRADICTS`` edge is meaningful rather than an error.
- Traversal and path discovery are breadth-first and track visited nodes
  so cycles cannot cause infinite loops.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from memos.domain.exceptions import NotFoundError, ValidationError
from memos.domain.memory import MemoryObject, RelationshipType
from memos.domain.relationship import Relationship
from memos.storage.protocols import GraphStore


class GraphEngine:
    """Validates and persists typed relationships, and runs graph queries.

    The engine is stateless between calls: all persistent state lives in the
    injected ``graph_store``. This keeps the engine independently testable
    and storage-agnostic.
    """

    def __init__(self, graph_store: GraphStore) -> None:
        self._graph_store: GraphStore = graph_store

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
        - ``weight`` must be ``>= 0`` (relationship weight is a
          non-negative signal strength; negative weights are meaningless).

        Self-loops are permitted; see module docstring for why.

        Args:
            source_id: Memory ID of the relationship source.
            target_id: Memory ID of the relationship target.
            relationship_type: Semantic type of the edge.
            weight: Non-negative edge weight (default ``1.0``).
            metadata: Optional application metadata attached to the edge.

        Returns:
            The persisted :class:`Relationship` (with assigned
            ``relationship_id`` and ``created_at``).

        Raises:
            ValidationError: if ``relationship_type`` is ``None`` or
                ``weight`` is negative.
        """
        if relationship_type is None:
            raise ValidationError(
                "relationship_type is required; every edge needs a semantic type"
            )
        if weight < 0:
            raise ValidationError(
                f"relationship weight must be >= 0, got {weight}"
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
                type value (e.g. ``"causes"``).
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
    ) -> List[Tuple[Relationship, int]]:
        """Breadth-first traversal from ``start_id`` over out-edges.

        Returns ``(edge, depth)`` pairs where ``depth`` is the number of
        hops from ``start_id`` to the edge's source. Visited nodes are
        tracked so cycles terminate.

        Args:
            start_id: Memory ID where traversal begins.
            max_depth: Maximum number of hops (default ``2``).
            relationship_types: Optional filter on relationship type values.

        Returns:
            List of ``(relationship, depth)`` tuples in BFS order.
        """
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
                if (
                    relationship_types is not None
                    and relationship.type.value not in relationship_types
                ):
                    continue
                output.append((relationship, depth + 1))
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


__all__ = ["GraphEngine"]
