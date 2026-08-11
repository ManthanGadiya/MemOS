"""In-memory graph store for development and testing.

Implements :class:`memos.storage.protocols.GraphStore`. Neo4j is the
production adapter and satisfies the same protocol.
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional, Tuple

from memos.domain.exceptions import StorageError
from memos.domain.memory import MemoryObject
from memos.domain.relationship import Relationship


class InMemoryGraphStore:
    """Thread-safe in-memory typed relationship graph."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._nodes: Dict[str, MemoryObject] = {}
        self._edges: Dict[str, Relationship] = {}

    # ---- node cache ------------------------------------------------------

    def cache_node(self, memory: MemoryObject) -> None:
        with self._lock:
            self._nodes[memory.memory_id] = memory

    def get_node(self, memory_id: str) -> Optional[MemoryObject]:
        """Return the cached node for ``memory_id`` or ``None``.

        Kernel-transaction before-image primitive: lets the transaction
        capture the graph node before a write and restore it on rollback.
        """
        with self._lock:
            return self._nodes.get(memory_id)

    # ---- GraphStore protocol ----------------------------------------------

    def upsert_relationship(self, rel: Relationship) -> None:
        with self._lock:
            self._edges[rel.relationship_id] = rel

    def delete_relationship(self, relationship_id: str) -> None:
        with self._lock:
            self._edges.pop(relationship_id, None)

    def delete_node(self, memory_id: str) -> None:
        with self._lock:
            self._nodes.pop(memory_id, None)
            self._edges = {
                rid: rel
                for rid, rel in self._edges.items()
                if rel.source_id != memory_id and rel.target_id != memory_id
            }

    def get_relationships(
        self,
        memory_id: Optional[str] = None,
        relationship_type: Optional[str] = None,
        direction: str = "any",
    ) -> List[Relationship]:
        with self._lock:
            results: List[Relationship] = []
            for rel in self._edges.values():
                if relationship_type is not None and rel.type.value != relationship_type:
                    continue
                if memory_id is None:
                    results.append(rel)
                    continue
                if direction == "out" and rel.source_id == memory_id:
                    results.append(rel)
                elif direction == "in" and rel.target_id == memory_id:
                    results.append(rel)
                elif direction == "any" and (rel.source_id == memory_id or rel.target_id == memory_id):
                    results.append(rel)
            results.sort(key=lambda r: r.created_at)
            return results

    def traverse(
        self,
        start_id: str,
        max_depth: int = 2,
        relationship_types: Optional[List[str]] = None,
    ) -> List[Tuple[Relationship, int]]:
        """Breadth-first traversal returning (edge, depth) pairs."""
        with self._lock:
            visited: set[str] = {start_id}
            frontier: List[Tuple[str, int]] = [(start_id, 0)]
            output: List[Tuple[Relationship, int]] = []
            while frontier:
                node, depth = frontier.pop(0)
                if depth >= max_depth:
                    continue
                for rel in self._edges.values():
                    if rel.source_id != node:
                        continue
                    if relationship_types and rel.type.value not in relationship_types:
                        continue
                    output.append((rel, depth + 1))
                    if rel.target_id not in visited:
                        visited.add(rel.target_id)
                        frontier.append((rel.target_id, depth + 1))
            return output

    def neighbors(
        self, memory_id: str, relationship_types: Optional[List[str]] = None, depth: int = 1
    ) -> List[MemoryObject]:
        related_ids: set[str] = set()
        for rel, d in self.traverse(memory_id, max_depth=depth, relationship_types=relationship_types):
            related_ids.add(rel.target_id)
        return [self._nodes[mid] for mid in related_ids if mid in self._nodes]

    def clear(self) -> None:
        with self._lock:
            self._nodes.clear()
            self._edges.clear()

    def close(self) -> None:
        pass


__all__ = ["InMemoryGraphStore"]