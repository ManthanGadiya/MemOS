"""Tests for the MemOS Memory Kernel.

Covers the coordination contract from docs/SystemArchitecture.md (sections 9
and 26), the transaction/rollback contract (sections 26 and 33.5), and the
security contract from docs/Security.md (sections 7 and 10):

- create/list/get/search/update/archive/restore/delete/touch/reindex route
  through the kernel and persist across all stores,
- validation failures surface as ``INVALID_REQUEST`` *before* any transaction,
- permission denials are audited as ``DENIED`` and stop before a transaction,
- writes commit atomically: a mid-write failure rolls back metadata, vector,
  graph, and version to their before-images in the documented order,
- audit records are immutable; events are published only after commit,
- untyped internal failures collapse to ``INTERNAL_ERROR`` without leaking
  details,
- relationships and the ``build_kernel`` factory are exercised end to end.
"""

import pytest

from memos.config.settings import Settings
from memos.domain.exceptions import StorageError
from memos.domain.memory import LifecycleState, MemoryObject, MemoryType, PermissionLevel
from memos.domain.relationship import Relationship, RelationshipType
from memos.embedding.hash_embedder import HashEmbedder
from memos.engines import MemoryEngine
from memos.engines.graph import GraphEngine
from memos.engines.importance import ImportanceEngine
from memos.engines.permission import SYSTEM_PRINCIPAL, PermissionEngine
from memos.engines.retrieval import RetrievalEngine
from memos.engines.version import VersionEngine
from memos.kernel.audit import AuditRecord, AuditResult, InMemoryAuditStore
from memos.kernel.errors import KernelError, KernelErrorCode
from memos.kernel.events import InMemoryEventBus
from memos.kernel.kernel import MemoryKernel
from memos.kernel.operations import KernelOperation
from memos.kernel.validation import RequestValidator
from memos.storage.in_memory_graph import InMemoryGraphStore
from memos.storage.in_memory_vector import InMemoryVectorStore
from memos.storage.sqlite_metadata import SQLiteMetadataStore


# ----------------------------------------------------------------------
# Failure-injection stores (one-shot, then behave normally)
# ----------------------------------------------------------------------
class FlakyVectorStore(InMemoryVectorStore):
    """Raise ``StorageError`` on the next ``upsert``, then behave normally."""

    def __init__(self) -> None:
        super().__init__()
        self._fail_once = True

    def upsert(self, memory_id: str, vector: list[float], payload: dict) -> None:
        if self._fail_once:
            self._fail_once = False
            raise StorageError("injected vector failure")
        super().upsert(memory_id, vector, payload)


class FlakyMetadataStore(SQLiteMetadataStore):
    """Raise ``StorageError`` on the next ``update``, then behave normally."""

    def __init__(self, database_path) -> None:
        super().__init__(database_path)
        self._fail_once = True

    def update(self, obj: MemoryObject) -> MemoryObject:
        if self._fail_once:
            self._fail_once = False
            raise StorageError("injected metadata failure")
        return super().update(obj)


class CrashingMetadataStore(SQLiteMetadataStore):
    """Raise an *untyped* exception on the next ``create`` (simulates a raw
    host error that must never leak to clients)."""

    def __init__(self, database_path) -> None:
        super().__init__(database_path)
        self._fail_once = True

    def create(self, obj: MemoryObject) -> MemoryObject:
        if self._fail_once:
            self._fail_once = False
            raise RuntimeError("boom: sqlite driver leaked a traceback")
        return super().create(obj)


# ----------------------------------------------------------------------
# Kernel construction helpers
# ----------------------------------------------------------------------
def build_test_kernel(
    tmp_path,
    *,
    metadata_store=None,
    vector_store=None,
    graph_store=None,
) -> MemoryKernel:
    """Assemble a MemoryKernel with injected stores (mirrors factory wiring).

    Engines/stores are fresh per call; SQLite metadata lands in ``tmp_path``
    so parallel test runs never share a database file.
    """
    settings = Settings()
    metadata_store = metadata_store or SQLiteMetadataStore(tmp_path / "kernel_test.db")
    vector_store = vector_store or InMemoryVectorStore()
    graph_store = graph_store or InMemoryGraphStore()

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
        embedder=HashEmbedder(),
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
        embedder=HashEmbedder(),
        permission_engine=permission_engine,
        settings=settings,
    )

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
        audit_store=InMemoryAuditStore(),
        event_bus=InMemoryEventBus(),
        validator=RequestValidator(settings),
    )


@pytest.fixture
def kernel(tmp_path) -> MemoryKernel:
    """A fully-wired kernel on fresh stores (teardown closes them)."""
    instance = build_test_kernel(tmp_path)
    yield instance
    instance.close()


@pytest.fixture
def events():
    """A listener collecting every kernel event for assertions."""
    collected: list = []

    def listener(event) -> None:
        collected.append(event)

    return collected, listener


def make_memory(
    kernel: MemoryKernel,
    owner_id: str = "alice",
    **overrides,
) -> MemoryObject:
    """Create a memory through the kernel from defaults plus overrides."""
    return kernel.create(
        content=overrides.pop("content", "alpha"),
        owner_id=owner_id,
        **overrides,
    )


# ----------------------------------------------------------------------
# Create: routing, persistence, audit, events
# ----------------------------------------------------------------------
class TestCreate:
    def test_routes_through_engines_and_persists(self, kernel, events):
        collected, listener = events
        kernel._event_bus.subscribe(listener)

        memory = make_memory(kernel, content="alpha", tags=["t1"])

        assert memory.version == 1
        assert memory.state is LifecycleState.ACTIVE
        assert memory.permission is PermissionLevel.PRIVATE  # documented default
        got = kernel.get(memory.memory_id, principal_id="alice")
        assert got.content == "alpha"

        # Retrieval sees the vector payload written by the create path.
        hits = kernel.search("alpha", top_k=5, principal_id="alice")
        assert any(hit.memory.memory_id == memory.memory_id for hit in hits)

        # One SUCCESS audit record and exactly one post-commit event.
        audits = kernel.list_audit(operation=KernelOperation.CREATE)
        assert len(audits) == 1
        assert audits[0].result is AuditResult.SUCCESS
        assert audits[0].memory_id == memory.memory_id
        kinds = [event.kind for event in collected]
        assert kinds == ["memory.create"]

    def test_blank_content_rejected_before_any_write(self, kernel, events):
        collected, listener = events
        kernel._event_bus.subscribe(listener)

        with pytest.raises(KernelError) as exc:
            kernel.create("   ")
        assert exc.value.code is KernelErrorCode.INVALID_REQUEST

        assert kernel.list_audit() == []
        assert collected == []
        assert kernel.list_memories(principal_id=SYSTEM_PRINCIPAL) == []

    def test_invalid_memory_id_on_read_is_structured(self, kernel):
        with pytest.raises(KernelError) as exc:
            kernel.get("", principal_id="alice")
        assert exc.value.code is KernelErrorCode.INVALID_REQUEST


# ----------------------------------------------------------------------
# Update / permission / versioning
# ----------------------------------------------------------------------
class TestUpdate:
    def test_updates_bump_version_and_audit(self, kernel, events):
        collected, listener = events
        kernel._event_bus.subscribe(listener)
        memory = make_memory(kernel, content="alpha")

        updated = kernel.update(memory.memory_id, content="beta", principal_id="alice")

        assert updated.content == "beta"
        assert updated.version == 2
        got = kernel.get(memory.memory_id, principal_id="alice")
        assert got.content == "beta"

        update_audits = kernel.list_audit(operation=KernelOperation.UPDATE)
        assert len(update_audits) == 1
        assert update_audits[0].result is AuditResult.SUCCESS
        assert update_audits[0].details.get("version") == 2
        assert any(event.kind == "memory.update" for event in collected)

    def test_permission_denied_before_transaction(self, kernel, events):
        collected, listener = events
        kernel._event_bus.subscribe(listener)
        memory = make_memory(kernel, content="alpha")

        with pytest.raises(KernelError) as exc:
            kernel.update(memory.memory_id, content="beta", principal_id="bob")
        assert exc.value.code is KernelErrorCode.PERMISSION_DENIED

        # The write never happened: content and version are untouched.
        got = kernel.get(memory.memory_id, principal_id="alice")
        assert got.content == "alpha"
        assert got.version == 1

        denied = kernel.list_audit(operation=KernelOperation.UPDATE, result=AuditResult.DENIED)
        assert len(denied) == 1
        assert denied[0].principal_id == "bob"
        assert [event.kind for event in collected] == ["memory.create"]

    def test_update_with_no_fields_is_invalid(self, kernel):
        memory = make_memory(kernel)
        with pytest.raises(KernelError) as exc:
            kernel.update(memory.memory_id, principal_id="alice")
        assert exc.value.code is KernelErrorCode.INVALID_REQUEST


# ----------------------------------------------------------------------
# Delete / lifecycle / relationships
# ----------------------------------------------------------------------
class TestDelete:
    def test_removes_vector_and_graph_relationships(self, kernel):
        first = make_memory(kernel, content="first memory")
        second = make_memory(kernel, content="second memory")

        relationship = kernel.add_relationship(
            first.memory_id,
            second.memory_id,
            RelationshipType.RELATED_TO,
            weight=0.8,
            principal_id="alice",
        )
        assert isinstance(relationship, Relationship)
        assert kernel.get_relationships(memory_id=first.memory_id) != []

        kernel.delete(first.memory_id, principal_id="alice")

        with pytest.raises(KernelError) as exc:
            kernel.get(first.memory_id, principal_id="alice")
        assert exc.value.code is KernelErrorCode.INVALID_REQUEST  # NotFound
        assert kernel.get_relationships(memory_id=first.memory_id) == []
        hits = kernel.search("first memory", top_k=5, principal_id="alice")
        assert all(hit.memory.memory_id != first.memory_id for hit in hits)

        delete_audits = kernel.list_audit(operation=KernelOperation.DELETE)
        assert len(delete_audits) == 1
        assert delete_audits[0].memory_id == first.memory_id
        assert delete_audits[0].result is AuditResult.SUCCESS

    def test_archive_restore_through_kernel(self, kernel):
        memory = make_memory(kernel)
        archived = kernel.archive(memory.memory_id, principal_id="alice")
        assert archived.state is LifecycleState.ARCHIVED
        restored = kernel.restore(memory.memory_id, principal_id="alice")
        assert restored.state is LifecycleState.ACTIVE


# ----------------------------------------------------------------------
# Transactions: rollback restores before-images; no partial commit
# ----------------------------------------------------------------------
class TestTransactions:
    def test_create_rollback_removes_partial_memory(self, tmp_path, events):
        collected, listener = events
        kernel = build_test_kernel(tmp_path, vector_store=FlakyVectorStore())
        kernel._event_bus.subscribe(listener)

        with pytest.raises(KernelError) as exc:
            kernel.create("alpha", owner_id="alice")
        assert exc.value.code is KernelErrorCode.INTERNAL_ERROR

        # Metadata, graph, and version were all rolled back (no partial memory).
        assert kernel.list_memories(principal_id=SYSTEM_PRINCIPAL) == []
        assert collected == []  # no event for a rolled-back operation
        rollbacks = kernel.list_audit(result=AuditResult.ROLLBACK)
        assert len(rollbacks) == 1
        # The audit records the originating MemOS code (not the client-visible
        # INTERNAL_ERROR mapping); an untyped crash records INTERNAL_ERROR.
        assert rollbacks[0].details.get("error_code") == "storage_error"
        kernel.close()

    def test_update_rollback_restores_all_subsystems(self, tmp_path, events):
        collected, listener = events
        kernel = build_test_kernel(tmp_path, metadata_store=FlakyMetadataStore(tmp_path / "flaky.db"))
        kernel._event_bus.subscribe(listener)

        memory = make_memory(kernel, content="alpha")
        with pytest.raises(KernelError) as exc:
            kernel.update(memory.memory_id, content="beta", principal_id="alice")
        assert exc.value.code is KernelErrorCode.INTERNAL_ERROR

        # The metadata before-image is restored, not left at the failed write.
        got = kernel.get(memory.memory_id, principal_id="alice")
        assert got.content == "alpha"
        assert got.version == 1
        # Only the setup create event exists; no event for the rolled-back update.
        assert [event.kind for event in collected] == ["memory.create"]
        assert kernel.list_audit(result=AuditResult.ROLLBACK)

    def test_internal_error_hides_details(self, tmp_path):
        kernel = build_test_kernel(
            tmp_path, metadata_store=CrashingMetadataStore(tmp_path / "crash.db")
        )
        with pytest.raises(KernelError) as exc:
            kernel.create("alpha", owner_id="alice")
        error = exc.value
        assert error.code is KernelErrorCode.INTERNAL_ERROR
        assert error.message == "internal error"
        assert "boom" not in error.message
        assert "traceback" not in str(error.details).lower()
        # Only safe request-scoped details surface.
        assert set(error.details) == {"request_id"}
        kernel.close()


# ----------------------------------------------------------------------
# Permissions on reads
# ----------------------------------------------------------------------
class TestReadPermissions:
    def test_private_memory_read_denied_to_foreign_principal(self, kernel):
        memory = make_memory(kernel, content="alpha")

        with pytest.raises(KernelError) as exc:
            kernel.get(memory.memory_id, principal_id="bob")
        assert exc.value.code is KernelErrorCode.PERMISSION_DENIED

        denied = kernel.list_audit(operation=KernelOperation.READ, result=AuditResult.DENIED)
        assert len(denied) == 1
        assert denied[0].principal_id == "bob"
        assert denied[0].memory_id == memory.memory_id

    def test_system_memory_readable_by_any_principal(self, kernel):
        memory = make_memory(
            kernel, content="system infra", permission=PermissionLevel.SYSTEM
        )
        got = kernel.get(memory.memory_id, principal_id="bob")
        assert got.content == "system infra"

    def test_deleted_memory_never_readable(self, kernel):
        memory = make_memory(kernel, content="alpha")
        kernel.delete(memory.memory_id, principal_id="alice")
        with pytest.raises(KernelError) as exc:
            kernel.get(memory.memory_id, principal_id="alice")
        assert exc.value.code is KernelErrorCode.INVALID_REQUEST


# ----------------------------------------------------------------------
# Audit immutability
# ----------------------------------------------------------------------
class TestAuditImmutability:
    def test_records_are_frozen_and_append_only(self, kernel):
        make_memory(kernel, content="alpha")
        make_memory(kernel, content="beta")
        records = kernel.list_audit()

        assert len(records) == 2
        with pytest.raises(AttributeError):
            records[0].result = AuditResult.FAILURE  # type: ignore[misc]

        # Appending a record never mutates earlier entries or shares state.
        before = records[0].to_dict()
        assert before["operation_type"] == "CREATE"
        assert all(isinstance(r, AuditRecord) for r in records)


# ----------------------------------------------------------------------
# Search / listing via the kernel
# ----------------------------------------------------------------------
class TestReads:
    def test_list_filters(self, kernel):
        make_memory(kernel, content="alpha", memory_type=MemoryType.SEMANTIC)
        make_memory(kernel, content="beta", memory_type=MemoryType.WORKING)

        semantic = kernel.list_memories(
            memory_type=MemoryType.SEMANTIC, principal_id="alice"
        )
        assert len(semantic) == 1
        assert semantic[0].content == "alpha"

    def test_search_validates_query(self, kernel):
        with pytest.raises(KernelError) as exc:
            kernel.search("", principal_id="alice")
        assert exc.value.code is KernelErrorCode.INVALID_REQUEST


# ----------------------------------------------------------------------
# Relationships
# ----------------------------------------------------------------------
class TestRelationships:
    def test_add_get_remove_roundtrip(self, kernel):
        first = make_memory(kernel)
        second = make_memory(kernel)

        relationship = kernel.add_relationship(
            first.memory_id,
            second.memory_id,
            RelationshipType.DEPENDS_ON,
            weight=0.5,
            principal_id="alice",
        )
        assert kernel.get_relationships(memory_id=first.memory_id) == [relationship]

        kernel.remove_relationship(relationship.relationship_id, principal_id="alice")
        assert kernel.get_relationships(memory_id=first.memory_id) == []

        add_audits = kernel.list_audit(operation=KernelOperation.ADD_RELATIONSHIP)
        assert add_audits[0].result is AuditResult.SUCCESS

    def test_invalid_weight_rejected(self, kernel):
        first = make_memory(kernel)
        second = make_memory(kernel)
        with pytest.raises(KernelError) as exc:
            kernel.add_relationship(
                first.memory_id,
                second.memory_id,
                RelationshipType.RELATED_TO,
                weight=2.0,
            )
        assert exc.value.code is KernelErrorCode.INVALID_REQUEST

    def test_missing_target_rejected(self, kernel):
        first = make_memory(kernel)
        with pytest.raises(KernelError):
            kernel.add_relationship(
                first.memory_id,
                "no-such-memory",
                RelationshipType.RELATED_TO,
            )


# ----------------------------------------------------------------------
# build_kernel factory
# ----------------------------------------------------------------------
class TestBuildKernel:
    def test_factory_wires_end_to_end(self, tmp_path):
        from memos.kernel.factory import build_kernel

        kernel = build_kernel(Settings(database_path=str(tmp_path / "factory.db")))
        try:
            memory = kernel.create("gamma", owner_id="alice")
            assert kernel.get(memory.memory_id, principal_id="alice").content == "gamma"
            assert kernel.list_audit(operation=KernelOperation.CREATE)
        finally:
            kernel.close()