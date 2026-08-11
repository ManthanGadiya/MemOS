"""SQLite metadata adapter.

Implements :class:`memos.storage.protocols.MetadataStore` on top of
SQLAlchemy 2.0 with a synchronous engine. Used for development and single-
process deployments; PostgreSQL is the production target (same protocol).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from memos.domain.exceptions import StorageError
from memos.domain.memory import (
    LifecycleState,
    MemoryObject,
    MemoryType,
    PermissionLevel,
    now_utc,
)


class Base(DeclarativeBase):
    pass


class MemoryRow(Base):
    __tablename__ = "memories"

    memory_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    namespace: Mapped[str] = mapped_column(String(64), default="personal", index=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    type: Mapped[str] = mapped_column(String(32), index=True)
    permission: Mapped[str] = mapped_column(String(32), default="private", index=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    tags: Mapped[str] = mapped_column(Text, default="[]")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Any] = mapped_column(DateTime(timezone=True))
    last_accessed_at: Mapped[Optional[Any]] = mapped_column(DateTime(timezone=True), nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    importance_category: Mapped[str] = mapped_column(String(32), default="medium")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    embedding_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class SQLiteMetadataStore:
    """SQLite-backed metadata store for development environments."""

    def __init__(self, database_path: str | Path) -> None:
        self._path = Path(database_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(
            f"sqlite:///{self._path}", connect_args={"check_same_thread": False}
        )
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)
        Base.metadata.create_all(self._engine)

    @staticmethod
    def _serialize_tags(tags: List[str]) -> str:
        return json.dumps(tags)

    @staticmethod
    def _deserialize_tags(raw: str) -> List[str]:
        try:
            return json.loads(raw or "[]")
        except json.JSONDecodeError:
            return []

    def _row_to_object(self, row: MemoryRow) -> MemoryObject:
        return MemoryObject(
            memory_id=row.memory_id,
            namespace=row.namespace,
            owner_id=row.owner_id,
            title=row.title,
            content=row.content,
            source=row.source,
            summary=row.summary,
            type=MemoryType(row.type),
            permission=PermissionLevel(row.permission),
            state=LifecycleState(row.state),
            tags=self._deserialize_tags(row.tags),
            metadata=json.loads(row.metadata_json or "{}"),
            version=row.version,
            created_at=row.created_at,
            updated_at=row.updated_at,
            last_accessed_at=row.last_accessed_at,
            access_count=row.access_count,
            importance=row.importance,
            importance_category=row.importance_category,
            confidence=row.confidence,
            embedding=json.loads(row.embedding_json) if row.embedding_json else None,
        )

    def _object_to_row(self, obj: MemoryObject) -> MemoryRow:
        return MemoryRow(
            memory_id=obj.memory_id,
            namespace=obj.namespace,
            owner_id=obj.owner_id,
            title=obj.title,
            content=obj.content,
            source=obj.source,
            summary=obj.summary,
            type=obj.type.value,
            permission=obj.permission.value,
            state=obj.state.value,
            tags=self._serialize_tags(obj.tags),
            metadata_json=json.dumps(obj.metadata, default=str),
            version=obj.version,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
            last_accessed_at=obj.last_accessed_at,
            access_count=obj.access_count,
            importance=obj.importance,
            importance_category=obj.importance_category,
            confidence=obj.confidence,
            embedding_json=json.dumps(obj.embedding) if obj.embedding else None,
        )

    # ---- MetadataStore protocol -----------------------------------------

    def create(self, obj: MemoryObject) -> MemoryObject:
        with self._session_factory() as session:
            session.add(self._object_to_row(obj))
            session.commit()
        return obj

    def get(self, memory_id: str) -> Optional[MemoryObject]:
        with self._session_factory() as session:
            row = session.get(MemoryRow, memory_id)
            return self._row_to_object(row) if row else None

    def update(self, obj: MemoryObject) -> MemoryObject:
        with self._session_factory() as session:
            row = session.get(MemoryRow, obj.memory_id)
            if row is None:
                raise StorageError(f"Memory {obj.memory_id} not found")
            new_row = self._object_to_row(obj)
            row.content = new_row.content
            row.type = new_row.type
            row.permission = new_row.permission
            row.state = new_row.state
            row.title = new_row.title
            row.source = new_row.source
            row.summary = new_row.summary
            row.namespace = new_row.namespace
            row.tags = new_row.tags
            row.metadata_json = new_row.metadata_json
            row.version = new_row.version
            row.updated_at = new_row.updated_at
            row.last_accessed_at = new_row.last_accessed_at
            row.access_count = new_row.access_count
            row.importance = new_row.importance
            row.importance_category = new_row.importance_category
            row.confidence = new_row.confidence
            row.embedding_json = new_row.embedding_json
            session.commit()
        return obj

    def delete(self, memory_id: str) -> None:
        with self._session_factory() as session:
            row = session.get(MemoryRow, memory_id)
            if row is None:
                raise StorageError(f"Memory {memory_id} not found")
            session.delete(row)
            session.commit()

    def list(
        self,
        owner_id: Optional[str] = None,
        memory_type: Optional[MemoryType] = None,
        state: Optional[LifecycleState] = None,
        tags: Optional[List[str]] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[MemoryObject]:
        with self._session_factory() as session:
            stmt = select(MemoryRow)
            if owner_id is not None:
                stmt = stmt.where(MemoryRow.owner_id == owner_id)
            if memory_type is not None:
                stmt = stmt.where(MemoryRow.type == memory_type.value)
            if state is not None:
                stmt = stmt.where(MemoryRow.state == state.value)
            stmt = stmt.order_by(MemoryRow.updated_at.desc()).limit(limit).offset(offset)
            rows = session.scalars(stmt).all()
            results = [self._row_to_object(r) for r in rows]
            if tags:
                results = [m for m in results if any(t in m.tags for t in tags)]
            return results

    def count(self, owner_id: Optional[str] = None) -> int:
        with self._session_factory() as session:
            stmt = select(MemoryRow.memory_id)
            if owner_id is not None:
                stmt = stmt.where(MemoryRow.owner_id == owner_id)
            return len(session.scalars(stmt).all())

    def search_metadata(self, query: str, limit: int = 20) -> List[MemoryObject]:
        """Case-insensitive substring search over content and tags."""
        with self._session_factory() as session:
            stmt = select(MemoryRow).where(MemoryRow.content.ilike(f"%{query}%"))
            stmt = stmt.order_by(MemoryRow.updated_at.desc()).limit(limit)
            return [self._row_to_object(r) for r in session.scalars(stmt).all()]

    def search_tags(self, tags: List[str], limit: int = 20) -> List[MemoryObject]:
        results: List[MemoryObject] = []
        with self._session_factory() as session:
            stmt = select(MemoryRow).order_by(MemoryRow.updated_at.desc()).limit(limit * 4)
            for row in session.scalars(stmt).all():
                if len(results) >= limit:
                    break
                if any(t in self._deserialize_tags(row.tags) for t in tags):
                    results.append(self._row_to_object(row))
        return results

    def close(self) -> None:
        self._engine.dispose()


__all__ = ["Base", "MemoryRow", "SQLiteMetadataStore"]