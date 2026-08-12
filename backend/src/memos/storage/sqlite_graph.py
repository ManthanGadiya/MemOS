"""SQLite-backed graph store.

Implements :class:`memos.storage.protocols.GraphStore` on top of SQLAlchemy.
The dev deployment now persists the typed relationship graph (edges and the
node cache used for neighbour resolution) to a real SQLite database instead of
holding them only in process memory, so the graph survives restarts. Neo4j
remains the production target and satisfies the same protocol.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    String,
    Text,
    create_engine,
    delete,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from memos.domain.exceptions import StorageError
from memos.domain.memory import MemoryObject
from memos.domain.relationship import Relationship


class Base(DeclarativeBase):
    pass


class GraphNodeRow(Base):
    __tablename__ = "graph_nodes"

    memory_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    object_json: Mapped[str] = mapped_column(Text)


class GraphEdgeRow(Base):
    __tablename__ = "graph_edges"

    relationship_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True))


class SQLiteGraphStore:
    """Persistent typed relationship graph backed by SQLite."""

    def __init__(self, database_path: str | Path) -> None:
        self._path = Path(database_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(
            f"sqlite:///{self._path}", connect_args={"check_same_thread": False}
        )
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)
        Base.metadata.create_all(self._engine)

    # ---- node cache ------------------------------------------------------

    def cache_node(self, memory: MemoryObject) -> None:
        """Persist the cached node for ``memory`` (transaction before-image)."""
        with self._session_factory() as session:
            row = session.get(GraphNodeRow, memory.memory_id)
            if row is None:
                row = GraphNodeRow(memory_id=memory.memory_id)
                session.add(row)
            row.object_json = json.dumps(memory.to_dict(), default=str)
            session.commit()

    def get_node(self, memory_id: str) -> Optional[MemoryObject]:
        """Return the cached node for ``memory_id`` or ``None``.

        Kernel-transaction before-image primitive: lets the transaction capture
        the graph node before a write and restore it on rollback.
        """
        with self._session_factory() as session:
            row = session.get(GraphNodeRow, memory_id)
            if row is None:
                return None
            return MemoryObject.from_dict(json.loads(row.object_json))

    # ---- GraphStore protocol ----------------------------------------------

    def upsert_relationship(self, rel: Relationship) -> None:
        with self._session_factory() as session:
            row = session.get(GraphEdgeRow, rel.relationship_id)
            if row is None:
                row = GraphEdgeRow(relationship_id=rel.relationship_id)
                session.add(row)
            row.source_id = rel.source_id
            row.target_id = rel.target_id
            row.type = rel.type.value
            row.weight = rel.weight
            row.metadata_json = json.dumps(rel.metadata, default=str)
            row.created_at = rel.created_at
            session.commit()

    def delete_relationship(self, relationship_id: str) -> None:
        with self._session_factory() as session:
            session.execute(
                delete(GraphEdgeRow).where(GraphEdgeRow.relationship_id == relationship_id)
            )
            session.commit()

    def delete_node(self, memory_id: str) -> None:
        with self._session_factory() as session:
            session.execute(
                delete(GraphNodeRow).where(GraphNodeRow.memory_id == memory_id)
            )
            session.execute(
                delete(GraphEdgeRow).where(
                    (GraphEdgeRow.source_id == memory_id)
                    | (GraphEdgeRow.target_id == memory_id)
                )
            )
            session.commit()

    def get_relationships(
        self,
        memory_id: Optional[str] = None,
        relationship_type: Optional[str] = None,
        direction: str = "any",
    ) -> List[Relationship]:
        with self._session_factory() as session:
            stmt = select(GraphEdgeRow)
            if relationship_type is not None:
                stmt = stmt.where(GraphEdgeRow.type == relationship_type)
            rows = session.scalars(stmt).all()
            results: List[Relationship] = []
            for row in rows:
                if memory_id is None:
                    results.append(self._row_to_relationship(row))
                    continue
                if direction == "out" and row.source_id == memory_id:
                    results.append(self._row_to_relationship(row))
                elif direction == "in" and row.target_id == memory_id:
                    results.append(self._row_to_relationship(row))
                elif direction == "any" and (
                    row.source_id == memory_id or row.target_id == memory_id
                ):
                    results.append(self._row_to_relationship(row))
            results.sort(key=lambda r: r.created_at)
            return results

    def traverse(
        self,
        start_id: str,
        max_depth: int = 2,
        relationship_types: Optional[List[str]] = None,
    ) -> List[Tuple[Relationship, int]]:
        """Breadth-first traversal returning ``(edge, depth)`` pairs."""
        with self._session_factory() as session:
            edge_rows = [self._row_to_relationship(r) for r in session.scalars(select(GraphEdgeRow)).all()]
        visited: set[str] = {start_id}
        frontier: List[Tuple[str, int]] = [(start_id, 0)]
        output: List[Tuple[Relationship, int]] = []
        while frontier:
            node, depth = frontier.pop(0)
            if depth >= max_depth:
                continue
            for rel in edge_rows:
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
        for rel, _ in self.traverse(memory_id, max_depth=depth, relationship_types=relationship_types):
            related_ids.add(rel.target_id)
        return [node for mid in related_ids if (node := self.get_node(mid)) is not None]

    def clear(self) -> None:
        with self._session_factory() as session:
            session.execute(delete(GraphEdgeRow))
            session.execute(delete(GraphNodeRow))
            session.commit()

    def close(self) -> None:
        self._engine.dispose()

    # ---- helpers ---------------------------------------------------------

    @staticmethod
    def _row_to_relationship(row: GraphEdgeRow) -> Relationship:
        return Relationship.from_dict(
            {
                "relationship_id": row.relationship_id,
                "source_id": row.source_id,
                "target_id": row.target_id,
                "type": row.type,
                "weight": row.weight,
                "metadata": json.loads(row.metadata_json),
                "created_at": row.created_at,
            }
        )


__all__ = ["Base", "GraphEdgeRow", "GraphNodeRow", "SQLiteGraphStore"]
