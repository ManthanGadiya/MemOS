"""SQLite-backed vector store.

Implements :class:`memos.storage.protocols.VectorStore` on top of SQLAlchemy,
mirroring the metadata adapter. The dev deployment now persists dense vectors to
a real SQLite database instead of holding them only in process memory, so the
vector index survives restarts. Qdrant remains the production target and
satisfies the same protocol.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import Column, String, Text, create_engine, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from memos.domain.exceptions import StorageError
from memos.storage.in_memory_vector import cosine_similarity


class Base(DeclarativeBase):
    pass


class VectorRow(Base):
    __tablename__ = "vectors"

    memory_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    vector_json: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class SQLiteVectorStore:
    """Persistent dense-vector similarity store backed by SQLite."""

    def __init__(self, database_path: str | Path) -> None:
        self._path = Path(database_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(
            f"sqlite:///{self._path}", connect_args={"check_same_thread": False}
        )
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)
        Base.metadata.create_all(self._engine)

    # ---- VectorStore protocol --------------------------------------------

    def upsert(self, memory_id: str, vector: List[float], payload: Dict[str, Any]) -> None:
        with self._session_factory() as session:
            row = session.get(VectorRow, memory_id)
            if row is None:
                row = VectorRow(memory_id=memory_id)
                session.add(row)
            row.vector_json = json.dumps(vector)
            row.payload_json = json.dumps(payload, default=str)
            session.commit()

    def delete(self, memory_id: str) -> None:
        with self._session_factory() as session:
            session.execute(delete(VectorRow).where(VectorRow.memory_id == memory_id))
            session.commit()

    def get(self, memory_id: str) -> Optional[Tuple[List[float], Dict[str, Any]]]:
        """Return ``(vector, payload)`` for ``memory_id`` or ``None``.

        Kernel-transaction before-image primitive: lets the transaction capture
        a vector entry before a write and restore it on rollback.
        """
        with self._session_factory() as session:
            row = session.get(VectorRow, memory_id)
            if row is None:
                return None
            return json.loads(row.vector_json), json.loads(row.payload_json)

    def search(
        self,
        vector: List[float],
        top_k: int = 10,
        filter_payload: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[str, float]]:
        with self._session_factory() as session:
            rows = session.scalars(select(VectorRow)).all()
            scored: List[Tuple[str, float]] = []
            for row in rows:
                if filter_payload:
                    payload = json.loads(row.payload_json)
                    if not all(payload.get(k) == v for k, v in filter_payload.items()):
                        continue
                stored = json.loads(row.vector_json)
                scored.append((row.memory_id, cosine_similarity(vector, stored)))
            scored.sort(key=lambda pair: pair[1], reverse=True)
            return scored[:top_k]

    def clear(self) -> None:
        with self._session_factory() as session:
            session.execute(delete(VectorRow))
            session.commit()

    def close(self) -> None:
        self._engine.dispose()


__all__ = ["Base", "VectorRow", "SQLiteVectorStore"]
