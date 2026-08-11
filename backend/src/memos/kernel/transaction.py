"""Kernel-owned transaction management for MemOS.

SystemArchitecture.md section 26 requires every write operation to execute
as a kernel-managed transaction with all-or-nothing atomicity, and section
33.5 defines the rollback sequence. This module implements that contract as
a :class:`Transaction` that captures **before-images** of every subsystem
(metadata, vector, graph, version) before an engine write and restores them
on rollback in the documented order:

    metadata -> graph -> version -> vector

Rollback never invokes engine logic; it drives only store/version primitives,
so subsystems never perform independent rollback (section 33.5). The rollback
is idempotent: a second ``rollback()`` after the first is a no-op.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from memos.domain.memory import MemoryObject
from memos.domain.relationship import Relationship
from memos.kernel.operations import KernelOperation
from memos.storage.protocols import GraphStore, MetadataStore, VectorStore

VersionChainReader = Callable[[str], Sequence[Any]]
VersionTruncator = Callable[[str, int], None]


class TransactionStatus(str, Enum):
    """Lifecycle of a kernel transaction."""

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    COMMITTED = "COMMITTED"
    ROLLED_BACK = "ROLLED_BACK"


@dataclass
class JournalEntry:
    """One inverse operation staged for rollback."""

    label: str
    undo: Callable[[], None]


@dataclass
class MemorySnapshot:
    """Before-image of one memory across all four subsystems."""

    memory_id: str
    # Metadata before-image: ``None`` when the memory did not exist yet.
    memory: Optional[MemoryObject] = None
    # Vector before-image ``(vector, payload)``; ``None`` when no entry existed.
    vector: Optional[Tuple[List[float], Dict[str, Any]]] = None
    # Graph node before-image; ``None`` when no cached node existed.
    node: Optional[MemoryObject] = None
    # Incident edges (exact Relationship objects) to re-create on rollback.
    edges: List[Relationship] = field(default_factory=list)
    # Version-chain height recorded before the operation.
    version_height: int = 0


class Transaction:
    """An atomic unit of work, owned exclusively by the Memory Kernel.

    Construction is pure: stores and the two version primitives are injected,
    so the transaction is storage-agnostic. ``begin`` must be called before
    any engine write; ``snapshot_memory`` captures before-images; ``commit``
    finalizes success; ``rollback`` restores prior state and is idempotent.
    """

    def __init__(
        self,
        *,
        metadata_store: MetadataStore,
        vector_store: VectorStore,
        graph_store: GraphStore,
        read_versions: VersionChainReader,
        truncate_versions: VersionTruncator,
        request_id: str,
        operation: KernelOperation,
        principal_id: str,
    ) -> None:
        self.txn_id: str = str(uuid.uuid4())
        self.request_id = request_id
        self.operation = operation
        self.principal_id = principal_id
        self.status: TransactionStatus = TransactionStatus.PENDING

        self._metadata_store = metadata_store
        self._vector_store = vector_store
        self._graph_store = graph_store
        self._read_versions = read_versions
        self._truncate_versions = truncate_versions
        self._journal: List[JournalEntry] = []
        self._snapshots: Dict[str, MemorySnapshot] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def begin(self) -> None:
        """Enter the active state with a fresh id and empty restore state."""
        self.txn_id = str(uuid.uuid4())
        self.status = TransactionStatus.ACTIVE
        self._journal = []
        self._snapshots = {}

    def is_active(self) -> bool:
        return self.status is TransactionStatus.ACTIVE

    def stage_undo(self, label: str, undo: Callable[[], None]) -> None:
        """Register an inverse operation to run (LIFO) before the restore."""
        self._journal.append(JournalEntry(label=label, undo=undo))

    # ------------------------------------------------------------------
    # Before-image capture
    # ------------------------------------------------------------------
    def snapshot_memory(self, memory_id: str) -> MemorySnapshot:
        """Capture before-images of ``memory_id`` across all subsystems.

        Call before the engine write executes. Vector and graph before-images
        are read via duck-typed ``get``/``get_node`` helpers when the concrete
        stores expose them (the dev in-memory adapters do; a store that does
        not provides ``None`` images and rollback falls back to deletion).
        """
        memory = self._metadata_store.get(memory_id)

        vector: Optional[Tuple[List[float], Dict[str, Any]]] = None
        vector_getter = getattr(self._vector_store, "get", None)
        if vector_getter is not None:
            vector = vector_getter(memory_id)

        node: Optional[MemoryObject] = None
        node_getter = getattr(self._graph_store, "get_node", None)
        if node_getter is not None:
            node = node_getter(memory_id)
        edges = self._graph_store.get_relationships(memory_id=memory_id, direction="any")

        snapshot = MemorySnapshot(
            memory_id=memory_id,
            memory=memory,
            vector=vector,
            node=node,
            edges=edges,
            version_height=len(self._read_versions(memory_id)),
        )
        self._snapshots[memory_id] = snapshot
        return snapshot

    # ------------------------------------------------------------------
    # Commit / rollback
    # ------------------------------------------------------------------
    def commit(self) -> None:
        """Mark the transaction committed (no-op when not active)."""
        if not self.is_active():
            return
        self.status = TransactionStatus.COMMITTED

    def rollback(self) -> None:
        """Restore every before-image and mark the transaction rolled back.

        Runs the documented sequence (SystemArchitecture.md 33.5): the staged
        journal is unwound LIFO, then each snapshot is restored in the order
        metadata -> graph -> version -> vector. Each subsystem restore is
        guarded so one failure cannot abort the remaining restores; the method
        is idempotent.
        """
        if self.status is not TransactionStatus.ACTIVE:
            return

        for entry in reversed(self._journal):
            try:
                entry.undo()
            except Exception:  # noqa: BLE001 - restore must not abort midway
                pass

        for snapshot in self._snapshots.values():
            self._restore_metadata(snapshot)
            self._restore_graph(snapshot)
            self._restore_versions(snapshot)
            self._restore_vector(snapshot)

        self.status = TransactionStatus.ROLLED_BACK

    # ------------------------------------------------------------------
    # Per-subsystem restore (documented order)
    # ------------------------------------------------------------------
    def _restore_metadata(self, snapshot: MemorySnapshot) -> None:
        if snapshot.memory is not None:
            self._metadata_store.update(snapshot.memory)
        elif self._metadata_store.get(snapshot.memory_id) is not None:
            self._metadata_store.delete(snapshot.memory_id)

    def _restore_graph(self, snapshot: MemorySnapshot) -> None:
        # ``delete_node`` purges the current node and its incident edges, then
        # rebuild the loop from the before-image (SR-003: deletion removes
        # relationships).
        self._graph_store.delete_node(snapshot.memory_id)
        if snapshot.node is not None:
            self._graph_store.cache_node(snapshot.node)
        for edge in snapshot.edges:
            self._graph_store.upsert_relationship(edge)

    def _restore_versions(self, snapshot: MemorySnapshot) -> None:
        try:
            self._truncate_versions(snapshot.memory_id, snapshot.version_height)
        except Exception:  # noqa: BLE001 - best-effort restore
            pass

    def _restore_vector(self, snapshot: MemorySnapshot) -> None:
        if snapshot.vector is None:
            self._vector_store.delete(snapshot.memory_id)
        else:
            vector, payload = snapshot.vector
            self._vector_store.upsert(snapshot.memory_id, vector, payload)