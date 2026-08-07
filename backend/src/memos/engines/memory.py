"""Memory Engine for MemOS.

The Memory Engine is the primary CRUD orchestrator: it manages Memory
Objects throughout their lifecycle (create / get / update / delete /
archive / restore) and coordinates the injected peer engines and stores.

Per ``docs/SystemArchitecture.md`` section 11 and ``docs/SRS.md`` section 11,
the Memory Engine:

- creates, validates, updates, archives, and deletes Memory Objects,
- manages lifecycle state transitions,
- orchestrates embedding generation, importance scoring, version
  recording, vector indexing, and graph node caching.

It deliberately does **not** re-implement:

- importance computation   (delegated to :class:`ImportanceEngine`),
- version history          (delegated to :class:`VersionEngine`),
- graph topology/traversal (delegated to :class:`GraphEngine`),
- authorization decisions  (delegated to :class:`PermissionEngine`).

The engine is storage-agnostic: it depends only on the storage protocols and
never imports a concrete adapter. Store failures surface as
:class:`~memos.domain.exceptions.StorageError` only where the failure is
meaningful to the caller; otherwise they propagate.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict

from memos.config.settings import Settings
from memos.domain.exceptions import NotFoundError, StorageError, ValidationError
from memos.domain.memory import (
    LifecycleState,
    MemoryObject,
    MemoryType,
    PermissionLevel,
    now_utc,
)
from memos.embedding.protocol import EmbeddingProvider
from memos.engines.graph import GraphEngine
from memos.engines.importance import ImportanceEngine
from memos.engines.permission import SYSTEM_PRINCIPAL, PermissionEngine
from memos.engines.version import VersionEngine
from memos.storage.protocols import GraphStore, MetadataStore, VectorStore

# Keys attached to every vector-store entry so the Retrieval Engine can
# filter candidates without touching the metadata store
# (docs/Algorithms.md section 6.1).
VECTOR_PAYLOAD_KEYS: tuple[str, ...] = (
    "memory_id",
    "type",
    "owner_id",
    "state",
    "importance",
    "confidence",
    "tags",
)


class MemoryEngine:
    """Orchestrates the memory lifecycle across stores and peer engines."""

    def __init__(
        self,
        metadata_store: MetadataStore,
        vector_store: VectorStore,
        graph_store: GraphStore,
        embedder: EmbeddingProvider,
        importance_engine: ImportanceEngine,
        version_engine: VersionEngine,
        graph_engine: GraphEngine,
        permission_engine: PermissionEngine,
        settings: Settings,
    ) -> None:
        self.metadata_store = metadata_store
        self.vector_store = vector_store
        self.graph_store = graph_store
        self.embedder = embedder
        self.importance_engine = importance_engine
        self.version_engine = version_engine
        self.graph_engine = graph_engine
        self.permission_engine = permission_engine
        # Retained for future tuning (e.g. retrieval defaults). The Version 1
        # engine does not yet consume any setting; it is injected so the
        # engine never re-reads configuration from global state.
        self._settings = settings

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(
        self,
        content: str,
        owner_id: str = "default",
        memory_type: MemoryType = MemoryType.SEMANTIC,
        namespace: str = "personal",
        title: str = "",
        source: str = "",
        summary: str = "",
        tags: list[str] | None = None,
        metadata: Dict[str, Any] | None = None,
        permission: PermissionLevel | None = None,
    ) -> MemoryObject:
        """Create a memory and persist it across all three stores.

        Flow: validate content -> build the object (state ACTIVE, version 1)
        -> compute embedding -> apply importance -> persist metadata ->
        upsert the vector entry -> cache the graph node -> record the
        ``create`` version.

        Defaults follow the domain contract (docs/SRS.md section 10):
        ``memory_type`` defaults to :attr:`MemoryType.SEMANTIC`, ``namespace``
        to ``"personal"``, and ``title``/``source``/``summary`` to empty
        strings. ``permission``, when omitted, resolves from
        ``settings.default_permission``.

        :raises ValidationError: if ``content`` is empty after ``strip()``.
        """
        self._validate_content(content)

        memory = MemoryObject(
            content=content,
            owner_id=owner_id,
            type=memory_type,
            namespace=namespace,
            title=title,
            source=source,
            summary=summary,
            permission=permission
            or PermissionLevel(self._settings.default_permission),
            tags=self._normalize_tags(tags),
            metadata=self._normalize_metadata(metadata),
            state=LifecycleState.ACTIVE,
            version=1,
        )
        memory.embedding = self._embed(memory.content)
        memory = self.importance_engine.update_memory(memory)

        self.metadata_store.create(memory)
        self._upsert_vector(memory)
        self._cache_graph_node(memory)
        self.version_engine.record(memory, change_type="create")
        return memory

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(
        self, memory_id: str, principal_id: str = SYSTEM_PRINCIPAL
    ) -> MemoryObject:
        """Fetch a memory, authorizing the read first.

        Flow: fetch -> ``require_access`` -> touch access stats -> recompute
        importance with the refreshed recency -> persist the refresh.

        :raises NotFoundError: if the memory does not exist.
        :raises PermissionDeniedError: if ``principal_id`` cannot read it.
        """
        memory = self._fetch_or_raise(memory_id)
        self.permission_engine.require_access(memory, principal_id)
        touched = self.touch_access(memory)
        refreshed = self.importance_engine.update_memory(touched)
        self.metadata_store.update(refreshed)
        # Keep the vector payload in sync with the refreshed metadata so
        # importance/confidence never drift between the two stores
        # (reviewer F22).
        self._refresh_vector_payload(refreshed)
        return refreshed

    def list_memories(
        self,
        owner_id: str | None = None,
        memory_type: MemoryType | None = None,
        state: LifecycleState | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
        principal_id: str = SYSTEM_PRINCIPAL,
    ) -> list[MemoryObject]:
        """List memories, delegating filters to the store and then applying
        permission filtering via :meth:`PermissionEngine.filter_accessible`."""
        memories = self.metadata_store.list(
            owner_id=owner_id,
            memory_type=memory_type,
            state=state,
            tags=tags,
            limit=limit,
            offset=offset,
        )
        return self.permission_engine.filter_accessible(memories, principal_id)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(
        self,
        memory_id: str,
        principal_id: str = SYSTEM_PRINCIPAL,
        *,
        content: str | None = None,
        tags: list[str] | None = None,
        metadata: Dict[str, Any] | None = None,
        memory_type: MemoryType | None = None,
        namespace: str | None = None,
        title: str | None = None,
        source: str | None = None,
        summary: str | None = None,
    ) -> MemoryObject:
        """Update content/tags/metadata/type/namespace/title/source/summary
        of an ACTIVE memory.

        ``memory_id`` is immutable and cannot be changed; ``namespace`` is a
        logical grouping and may be updated.

        Flow: fetch -> ``require_modify`` -> lifecycle check (LC-006: only
        ACTIVE memories receive updates) -> build a new object with the next
        version -> recompute embedding and importance when content changes ->
        persist, refresh the vector payload and cached graph node, and record
        an ``update`` version snapshot.

        :raises NotFoundError: if the memory does not exist.
        :raises PermissionDeniedError: if ``principal_id`` cannot modify it.
        :raises ValidationError: if no field is provided, ``content`` is
            blank, or the memory is not ACTIVE.
        """
        current = self._fetch_or_raise(memory_id)
        self.permission_engine.require_modify(current, principal_id)
        self._require_state(current, LifecycleState.ACTIVE)

        if content is not None:
            self._validate_content(content)
        if (
            content is None
            and tags is None
            and metadata is None
            and memory_type is None
            and namespace is None
            and title is None
            and source is None
            and summary is None
        ):
            raise ValidationError(
                f"update for memory {memory_id!r} provides no fields to change"
            )

        content_changed = content is not None and content != current.content

        updated = replace(
            current,
            content=content if content is not None else current.content,
            namespace=namespace if namespace is not None else current.namespace,
            title=title if title is not None else current.title,
            source=source if source is not None else current.source,
            summary=summary if summary is not None else current.summary,
            tags=(
                self._normalize_tags(tags)
                if tags is not None
                else list(current.tags)
            ),
            metadata=(
                self._normalize_metadata(metadata)
                if metadata is not None
                else dict(current.metadata)
            ),
            type=memory_type if memory_type is not None else current.type,
            version=current.version + 1,
            updated_at=now_utc(),
        )
        if content_changed:
            updated.embedding = self._embed(updated.content)
            updated = self.importance_engine.update_memory(updated)

        self.metadata_store.update(updated)
        self._upsert_vector(updated)
        self._cache_graph_node(updated)
        self.version_engine.record(updated, change_type="update", previous=current)
        return updated

    # ------------------------------------------------------------------
    # Lifecycle transitions
    # ------------------------------------------------------------------

    def delete(self, memory_id: str, principal_id: str = SYSTEM_PRINCIPAL) -> None:
        """Soft-delete a memory: ACTIVE/ARCHIVED -> DELETED.

        The row is kept with ``state=DELETED`` (V1 performs logical deletion,
        SRS section 11.4) but the memory is removed from the vector and graph
        stores so it never participates in retrieval (LC-004). A ``delete``
        version snapshot is recorded. DELETED is terminal; further
        transitions raise :class:`ValidationError`.

        :raises NotFoundError: if the memory does not exist.
        :raises PermissionDeniedError: if ``principal_id`` cannot modify it.
        :raises ValidationError: if the lifecycle transition is invalid.
        """
        current = self._fetch_or_raise(memory_id)
        self.permission_engine.require_modify(current, principal_id)
        self._require_transition(current.state, LifecycleState.DELETED)

        deleted = replace(
            current,
            state=LifecycleState.DELETED,
            version=current.version + 1,
            updated_at=now_utc(),
        )
        self.metadata_store.update(deleted)
        self.vector_store.delete(memory_id)
        self.graph_store.delete_node(memory_id)
        self.version_engine.record(deleted, change_type="delete", previous=current)

    def archive(
        self, memory_id: str, principal_id: str = SYSTEM_PRINCIPAL
    ) -> MemoryObject:
        """Transition a memory ACTIVE -> ARCHIVED.

        Archived memories remain stored and explicitly retrievable but are
        excluded from default retrieval (LC-005); the vector payload is
        refreshed with the new state so the Retrieval Engine can filter.

        :raises NotFoundError: if the memory does not exist.
        :raises PermissionDeniedError: if ``principal_id`` cannot modify it.
        :raises ValidationError: if the lifecycle transition is invalid.
        """
        current = self._fetch_or_raise(memory_id)
        self.permission_engine.require_modify(current, principal_id)
        self._require_transition(current.state, LifecycleState.ARCHIVED)

        archived = replace(
            current,
            state=LifecycleState.ARCHIVED,
            version=current.version + 1,
            updated_at=now_utc(),
        )
        self.metadata_store.update(archived)
        self._upsert_vector(archived)
        self._cache_graph_node(archived)
        self.version_engine.record(archived, change_type="archive", previous=current)
        return archived

    def restore(
        self, memory_id: str, principal_id: str = SYSTEM_PRINCIPAL
    ) -> MemoryObject:
        """Transition a memory ARCHIVED -> ACTIVE.

        :raises NotFoundError: if the memory does not exist.
        :raises PermissionDeniedError: if ``principal_id`` cannot modify it.
        :raises ValidationError: if the lifecycle transition is invalid.
        """
        current = self._fetch_or_raise(memory_id)
        self.permission_engine.require_modify(current, principal_id)
        self._require_transition(current.state, LifecycleState.ACTIVE)

        restored = replace(
            current,
            state=LifecycleState.ACTIVE,
            version=current.version + 1,
            updated_at=now_utc(),
        )
        self.metadata_store.update(restored)
        self._upsert_vector(restored)
        self._cache_graph_node(restored)
        self.version_engine.record(restored, change_type="restore", previous=current)
        return restored

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def touch_access(self, memory: MemoryObject) -> MemoryObject:
        """Increment ``access_count`` and refresh ``last_accessed_at``.

        The updated object is persisted before being returned.
        """
        touched = replace(
            memory,
            access_count=memory.access_count + 1,
            last_accessed_at=now_utc(),
        )
        self.metadata_store.update(touched)
        return touched

    def reindex(
        self, memory_id: str, principal_id: str = SYSTEM_PRINCIPAL
    ) -> MemoryObject:
        """Recompute the embedding from the current content and re-upsert the
        vector entry (used after importance/version changes).

        Authorization is enforced before any re-indexing (docs/Security.md
        SP-002: no component may bypass permission validation), mirroring the
        modify check applied by :meth:`update`.

        The recomputed embedding is persisted to the metadata store so the
        stored object and the vector entry never diverge.

        :raises NotFoundError: if the memory does not exist.
        :raises PermissionDeniedError: if ``principal_id`` cannot modify it.
        """
        memory = self._fetch_or_raise(memory_id)
        self.permission_engine.require_modify(memory, principal_id)
        reindexed = replace(memory, embedding=self._embed(memory.content))
        self.metadata_store.update(reindexed)
        self._upsert_vector(reindexed)
        self._cache_graph_node(reindexed)
        return reindexed

    # ------------------------------------------------------------------
    # Validation & lifecycle helpers
    # ------------------------------------------------------------------

    def _validate_content(self, content: str) -> None:
        """Reject empty or non-string content (must survive ``strip()``)."""
        if not isinstance(content, str) or not content.strip():
            raise ValidationError("memory content must be a non-empty string")

    def _require_state(self, memory: MemoryObject, expected: LifecycleState) -> None:
        """Enforce that ``memory`` is in a specific (state-preserving) state.

        Used for operations that do not change state but are only legal in
        one state (e.g. LC-006: only ACTIVE memories may receive updates).
        """
        if memory.state is not expected:
            raise ValidationError(
                f"memory {memory.memory_id!r} must be in state {expected.value!r} "
                f"for this operation; current state is {memory.state.value!r}"
            )

    def _require_transition(
        self, from_state: LifecycleState, to_state: LifecycleState
    ) -> None:
        """Enforce a documented lifecycle transition (SRS section 11.5, LC-002).

        ``LifecycleState.valid_transitions`` is the single source of truth for
        which transitions exist; DELETED is terminal because it has no
        outgoing transitions.
        """
        if to_state not in LifecycleState.valid_transitions(from_state):
            raise ValidationError(
                f"invalid lifecycle transition {from_state.value!r} -> "
                f"{to_state.value!r}"
            )

    @staticmethod
    def _normalize_tags(
        tags: list[str] | tuple[str, ...] | set[str] | None,
    ) -> list[str]:
        """Coerce a tags collection to a fresh list (never a bare string)."""
        if tags is None:
            return []
        if isinstance(tags, str):
            raise ValidationError(
                "tags must be a collection of strings, not a single string"
            )
        return list(tags)

    @staticmethod
    def _normalize_metadata(metadata: Dict[str, Any] | None) -> Dict[str, Any]:
        """Coerce metadata to a fresh dict, guarding against non-dict input."""
        if metadata is None:
            return {}
        if not isinstance(metadata, dict):
            raise ValidationError("metadata must be a dictionary")
        return dict(metadata)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _fetch_or_raise(self, memory_id: str) -> MemoryObject:
        """Return the stored memory or raise :class:`NotFoundError`."""
        memory = self.metadata_store.get(memory_id)
        if memory is None:
            raise NotFoundError(f"Memory {memory_id!r} not found")
        return memory

    def _embed(self, content: str) -> list[float]:
        """Embed ``content`` via the injected provider."""
        return self.embedder.embed(content)

    def _build_vector_payload(self, memory: MemoryObject) -> Dict[str, Any]:
        """Payload attached to the vector entry for retrieval filtering.

        Keys mirror :data:`VECTOR_PAYLOAD_KEYS`; enums are stored as their
        string values so payloads stay JSON-safe across adapters.
        """
        return {
            "memory_id": memory.memory_id,
            "type": memory.type.value,
            "owner_id": memory.owner_id,
            "state": memory.state.value,
            "importance": memory.importance,
            "confidence": memory.confidence,
            "tags": list(memory.tags),
        }

    def _upsert_vector(self, memory: MemoryObject) -> None:
        """Persist the memory's embedding and filter payload to the vector store."""
        if memory.embedding is None:
            raise StorageError(
                f"cannot index memory {memory.memory_id!r}: embedding is missing"
            )
        self.vector_store.upsert(
            memory.memory_id, memory.embedding, self._build_vector_payload(memory)
        )

    def _refresh_vector_payload(self, memory: MemoryObject) -> None:
        """Re-upsert a memory's filter payload without recomputing the
        embedding, keeping vector-store importance/confidence aligned with the
        metadata store (reviewer F22).

        No-op when the memory has no embedding (nothing to index).
        """
        if memory.embedding is not None:
            self.vector_store.upsert(
                memory.memory_id,
                memory.embedding,
                self._build_vector_payload(memory),
            )

    def _cache_graph_node(self, memory: MemoryObject) -> None:
        """Refresh the cached graph node when the adapter supports it.

        ``cache_node`` is an adapter extension (not part of the GraphStore
        protocol), so the engine duck-types the check and degrades gracefully
        when the adapter lacks it.
        """
        cache_node = getattr(self.graph_store, "cache_node", None)
        if callable(cache_node):
            cache_node(memory)


__all__ = ["MemoryEngine"]
