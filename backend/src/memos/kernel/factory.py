"""Convenience wiring for the Memory Kernel.

``build_kernel`` assembles a fully-wired :class:`MemoryKernel` instance using
the development in-memory adapters. The REST API, MCP server, and integration
tests import this single function — no other component constructs the kernel
object graph directly.
"""

from __future__ import annotations

from memos.config.settings import Settings
from memos.embedding.hash_embedder import HashEmbedder
from memos.engines.graph import GraphEngine
from memos.engines.importance import ImportanceEngine
from memos.engines.memory import MemoryEngine
from memos.engines.permission import PermissionEngine
from memos.engines.retrieval import RetrievalEngine
from memos.engines.version import VersionEngine
from memos.kernel.audit import AuditStore, InMemoryAuditStore
from memos.kernel.events import EventBus, InMemoryEventBus
from memos.kernel.kernel import MemoryKernel
from memos.kernel.validation import RequestValidator
from memos.storage.in_memory_graph import InMemoryGraphStore
from memos.storage.in_memory_vector import InMemoryVectorStore
from memos.storage.protocols import GraphStore, MetadataStore, VectorStore
from memos.storage.sqlite_metadata import SQLiteMetadataStore


def _resolve_metadata_store(settings: Settings) -> MetadataStore:
    """Return a metadata store instance per the configured backend."""
    backend = (settings.storage_backend or "sqlite").lower()
    if backend in {"sqlite", "memory"}:
        return SQLiteMetadataStore(settings.database_path)
    raise ValueError(f"unsupported storage_backend: {backend!r}")


def build_kernel(settings: Optional[Settings] = None) -> MemoryKernel:
    """Create a fully-wired MemoryKernel with dev adapters.

    Args:
        settings: Optional :class:`Settings`. When ``None``, a default
            configuration is built (honouring ``MEMOS_`` env vars).

    Returns:
        A ready-to-use :class:`MemoryKernel` with all engines, stores, audit,
        and event bus injected.
    """
    if settings is None:
        settings = Settings()

    from memos.domain.memory import LifecycleState

    embedder = HashEmbedder(dimension=settings.embedding_dimension)

    metadata_store: MetadataStore = _resolve_metadata_store(settings)
    vector_store: VectorStore = InMemoryVectorStore()
    graph_store: GraphStore = InMemoryGraphStore()

    permission_engine = PermissionEngine(settings)
    importance_engine = ImportanceEngine(settings)
    version_engine = VersionEngine()
    graph_engine = GraphEngine(
        graph_store,
        node_validator=lambda mid: (m := metadata_store.get(mid)) is not None
        and m.state is LifecycleState.ACTIVE,
    )

    memory_engine = MemoryEngine(
        metadata_store=metadata_store,
        vector_store=vector_store,
        graph_store=graph_store,
        embedder=embedder,
        importance_engine=importance_engine,
        version_engine=version_engine,
        graph_engine=graph_engine,
        permission_engine=permission_engine,
        settings=settings,
    )

    retrieval_engine = RetrievalEngine(
        metadata_store=metadata_store,
        vector_store=vector_store,
        graph_engine=graph_engine,
        embedder=embedder,
        permission_engine=permission_engine,
        settings=settings,
    )

    audit_store: AuditStore = InMemoryAuditStore()
    event_bus: EventBus = InMemoryEventBus()
    validator = RequestValidator(settings)

    return MemoryKernel(
        settings=settings,
        memory_engine=memory_engine,
        version_engine=version_engine,
        importance_engine=importance_engine,
        graph_engine=graph_engine,
        permission_engine=permission_engine,
        retrieval_engine=retrieval_engine,
        metadata_store=metadata_store,
        vector_store=vector_store,
        graph_store=graph_store,
        audit_store=audit_store,
        event_bus=event_bus,
        validator=validator,
    )


__all__ = ["build_kernel"]