"""Tests for the MemOS Memory Engine.

Covers the CRUD orchestration contract from docs/SystemArchitecture.md
(section 11) and the lifecycle rules from docs/SRS.md (section 11):

- create persists across metadata/vector/graph stores and records version 1,
- empty content raises ValidationError,
- get authorizes, touches access stats, and refreshes importance,
- update changes content, bumps the version, and records an ``update``,
- delete soft-deletes and removes vector/graph entries,
- archive/restore follow the documented lifecycle state machine,
- permission denials are enforced on read/modify operations,
- listing applies filters and permission filtering.
"""

import pytest

from memos.config.settings import Settings
from memos.domain.exceptions import (
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from memos.domain.memory import LifecycleState, MemoryObject, MemoryType, PermissionLevel
from memos.embedding.hash_embedder import HashEmbedder
from memos.engines import MemoryEngine
from memos.engines.graph import GraphEngine
from memos.engines.importance import ImportanceEngine
from memos.engines.permission import SYSTEM_PRINCIPAL, PermissionEngine
from memos.engines.version import VersionEngine
from memos.storage.in_memory_graph import InMemoryGraphStore
from memos.storage.in_memory_vector import InMemoryVectorStore
from memos.storage.sqlite_metadata import SQLiteMetadataStore


@pytest.fixture
def engine(tmp_path) -> MemoryEngine:
    """A fully wired backend stack on fresh temp/in-memory stores."""
    settings = Settings()
    graph_store = InMemoryGraphStore()
    return MemoryEngine(
        metadata_store=SQLiteMetadataStore(tmp_path / "memos_test.db"),
        vector_store=InMemoryVectorStore(),
        graph_store=graph_store,
        embedder=HashEmbedder(),
        importance_engine=ImportanceEngine(settings),
        version_engine=VersionEngine(),
        graph_engine=GraphEngine(graph_store),
        permission_engine=PermissionEngine(settings),
        settings=settings,
    )


def make_memory(
    engine: MemoryEngine,
    content: str = "alpha",
    owner_id: str = "alice",
    **overrides: object,
) -> MemoryObject:
    """Create a memory from defaults plus explicit overrides."""
    params: dict[str, object] = {
        "content": content,
        "owner_id": owner_id,
        "tags": ["work"],
        "metadata": {"source": "user"},
    }
    params.update(overrides)
    return engine.create(**params)  # type: ignore[arg-type]


def vector_contains(engine: MemoryEngine, content: str, memory_id: str) -> bool:
    """Whether ``memory_id`` is retrievable from the vector store."""
    hits = engine.vector_store.search(engine.embedder.embed(content), top_k=50)
    return memory_id in {mid for mid, _ in hits}


# ----------------------------------------------------------------------
# create
# ----------------------------------------------------------------------


class TestCreate:
    def test_create_persists_across_all_stores_with_version_one_and_importance(
        self, engine: MemoryEngine
    ) -> None:
        created = make_memory(engine, content="the cat sat on the mat")

        assert created.version == 1
        assert created.state is LifecycleState.ACTIVE
        # Importance was computed and stored (never the 0.5 default).
        assert created.importance != 0.5
        assert created.importance_category in {"low", "medium", "high"}

        # Metadata store holds the row.
        persisted = engine.metadata_store.get(created.memory_id)
        assert persisted is not None
        assert persisted.content == created.content

        # Vector store holds an entry retrievable by the content embedding.
        assert vector_contains(engine, created.content, created.memory_id)

        # Graph node is cached.
        assert created.memory_id in engine.graph_store._nodes  # type: ignore[attr-defined]

        # Version 1 'create' snapshot is recorded.
        versions = engine.version_engine.list_versions(created.memory_id)
        assert [entry.version for entry in versions] == [1]
        assert versions[0].change_type == "create"

    def test_create_embedding_matches_content(self, engine: MemoryEngine) -> None:
        created = make_memory(engine, content="unique content phrase")
        assert created.embedding == engine.embedder.embed("unique content phrase")

    def test_create_defaults_to_semantic(self, engine: MemoryEngine) -> None:
        created = make_memory(engine, content="default type")
        assert created.type is MemoryType.SEMANTIC

    def test_create_accepts_namespace_title_source_summary_round_trips(
        self, engine: MemoryEngine
    ) -> None:
        created = make_memory(
            engine,
            content="round trip",
            namespace="research",
            title="A Title",
            source="test-suite",
            summary="A short summary",
        )

        assert created.namespace == "research"
        assert created.title == "A Title"
        assert created.source == "test-suite"
        assert created.summary == "A short summary"

        persisted = engine.metadata_store.get(created.memory_id)
        assert persisted.namespace == "research"
        assert persisted.title == "A Title"
        assert persisted.source == "test-suite"
        assert persisted.summary == "A short summary"

    def test_create_default_namespace_title_source_summary(
        self, engine: MemoryEngine
    ) -> None:
        created = make_memory(engine, content="default metadata fields")
        assert created.namespace == "personal"
        assert created.title == ""
        assert created.source == ""
        assert created.summary == ""

    def test_create_with_none_permission_uses_settings_default(
        self, engine: MemoryEngine
    ) -> None:
        created = make_memory(engine, content="default permission", permission=None)
        assert created.permission is PermissionLevel(engine._settings.default_permission)

    def test_create_with_explicit_permission_is_respected(
        self, engine: MemoryEngine
    ) -> None:
        created = make_memory(
            engine,
            content="explicit permission",
            permission=PermissionLevel.SYSTEM,
        )
        assert created.permission is PermissionLevel.SYSTEM

    def test_create_rejects_empty_content(self, engine: MemoryEngine) -> None:
        for blank in ("", "   ", "\n\t"):
            with pytest.raises(ValidationError):
                engine.create(content=blank)

    def test_vector_payload_exposes_retrieval_filters(
        self, engine: MemoryEngine
    ) -> None:
        created = make_memory(
            engine,
            owner_id="alice",
            content="payload check",
            memory_type=MemoryType.SEMANTIC,
            tags=["x", "y"],
        )
        payload = engine.vector_store._payloads[created.memory_id]  # type: ignore[attr-defined]
        assert set(payload) == {
            "memory_id",
            "type",
            "owner_id",
            "state",
            "importance",
            "confidence",
            "tags",
        }
        assert payload["memory_id"] == created.memory_id
        assert payload["type"] == "semantic"
        assert payload["owner_id"] == "alice"
        assert payload["state"] == "active"
        assert payload["importance"] == created.importance
        assert payload["confidence"] == created.confidence
        assert payload["tags"] == ["x", "y"]


# ----------------------------------------------------------------------
# get
# ----------------------------------------------------------------------


class TestGet:
    def test_get_returns_memory_and_increments_access_count(
        self, engine: MemoryEngine
    ) -> None:
        created = make_memory(engine)

        first = engine.get(created.memory_id)
        assert first.content == created.content
        assert first.access_count == 1
        assert first.last_accessed_at is not None

        second = engine.get(created.memory_id)
        assert second.access_count == 2

        # The touch is persisted, not just returned.
        assert engine.metadata_store.get(created.memory_id).access_count == 2

    def test_get_missing_memory_raises_not_found(self, engine: MemoryEngine) -> None:
        with pytest.raises(NotFoundError):
            engine.get("missing-id")

    def test_get_refreshes_importance_from_updated_recency(
        self, engine: MemoryEngine
    ) -> None:
        created = make_memory(engine)

        fetched = engine.get(created.memory_id)

        # The returned importance equals a fresh computation on the touched
        # object (access_count=1, last_accessed_at set), up to the sub-second
        # drift of the recency factor between the two computations.
        expected = engine.importance_engine.update_memory(
            engine.metadata_store.get(created.memory_id)
        )
        assert fetched.importance == pytest.approx(expected.importance, abs=1e-4)
        assert fetched.importance_category == expected.importance_category

    def test_get_refreshes_vector_payload_importance(self, engine: MemoryEngine) -> None:
        created = make_memory(engine, content="payload refresh check")
        payload_before = engine.vector_store._payloads[created.memory_id]  # type: ignore[attr-defined]

        fetched = engine.get(created.memory_id)

        # The refreshed importance (recomputed after access_count=1) is
        # persisted to metadata AND mirrored into the vector payload so the
        # two stores never drift (reviewer F22).
        payload_after = engine.vector_store._payloads[created.memory_id]  # type: ignore[attr-defined]
        assert payload_after["importance"] == fetched.importance
        assert payload_after["confidence"] == fetched.confidence
        assert engine.metadata_store.get(created.memory_id).importance == fetched.importance
        # Access/recency changed the recomputed importance vs. creation time.
        assert payload_after["importance"] != payload_before["importance"]


# ----------------------------------------------------------------------
# update
# ----------------------------------------------------------------------


class TestUpdate:
    def test_update_changes_content_bumps_version_and_records_update(
        self, engine: MemoryEngine
    ) -> None:
        created = make_memory(engine, content="before")

        updated = engine.update(created.memory_id, content="after")

        assert updated.version == 2
        assert updated.content == "after"
        assert updated.embedding == engine.embedder.embed("after")

        persisted = engine.metadata_store.get(created.memory_id)
        assert persisted.content == "after"
        assert persisted.version == 2
        # The cached graph node reflects the new content.
        assert engine.graph_store._nodes[created.memory_id].content == "after"  # type: ignore[attr-defined]

        versions = engine.version_engine.list_versions(created.memory_id)
        assert [entry.version for entry in versions] == [1, 2]
        assert versions[-1].change_type == "update"
        assert versions[-1].diff["content"] == ["before", "after"]

        # The vector entry matches the new embedding.
        assert vector_contains(engine, "after", created.memory_id)

    def test_update_keeps_embedding_when_content_unchanged(
        self, engine: MemoryEngine
    ) -> None:
        created = make_memory(engine, content="stable")

        updated = engine.update(created.memory_id, tags=["new-tag"])

        assert updated.content == "stable"
        assert updated.tags == ["new-tag"]
        assert updated.embedding == engine.embedder.embed("stable")
        assert updated.version == 2

    def test_update_requires_at_least_one_field(self, engine: MemoryEngine) -> None:
        created = make_memory(engine)
        with pytest.raises(ValidationError):
            engine.update(created.memory_id)

    def test_update_rejects_blank_content(self, engine: MemoryEngine) -> None:
        created = make_memory(engine)
        with pytest.raises(ValidationError):
            engine.update(created.memory_id, content="   ")

    def test_update_missing_memory_raises_not_found(
        self, engine: MemoryEngine
    ) -> None:
        with pytest.raises(NotFoundError):
            engine.update("missing-id", content="x")

    def test_update_rejected_when_not_active(self, engine: MemoryEngine) -> None:
        # LC-006: only ACTIVE memories may receive updates.
        created = make_memory(engine)
        engine.archive(created.memory_id)
        with pytest.raises(ValidationError):
            engine.update(created.memory_id, content="nope")


# ----------------------------------------------------------------------
# delete
# ----------------------------------------------------------------------


class TestDelete:
    def test_delete_soft_deletes_and_removes_indexes(
        self, engine: MemoryEngine
    ) -> None:
        created = make_memory(engine)

        engine.delete(created.memory_id)

        # The row is kept with state=DELETED (logical deletion).
        persisted = engine.metadata_store.get(created.memory_id)
        assert persisted is not None
        assert persisted.state is LifecycleState.DELETED
        assert persisted.version == 2

        # Removed from vector and graph stores.
        assert not vector_contains(engine, created.content, created.memory_id)
        assert created.memory_id not in engine.graph_store._nodes  # type: ignore[attr-defined]

        versions = engine.version_engine.list_versions(created.memory_id)
        assert versions[-1].change_type == "delete"
        assert versions[-1].diff["state"] == ["active", "deleted"]

    def test_delete_is_terminal(self, engine: MemoryEngine) -> None:
        created = make_memory(engine)
        engine.delete(created.memory_id)

        with pytest.raises(ValidationError):
            engine.delete(created.memory_id)
        with pytest.raises(ValidationError):
            engine.update(created.memory_id, content="zombie")
        with pytest.raises(ValidationError):
            engine.archive(created.memory_id)
        with pytest.raises(ValidationError):
            engine.restore(created.memory_id)

    def test_delete_allowed_from_archived(self, engine: MemoryEngine) -> None:
        created = make_memory(engine)
        engine.archive(created.memory_id)

        engine.delete(created.memory_id)

        assert (
            engine.metadata_store.get(created.memory_id).state
            is LifecycleState.DELETED
        )

    def test_delete_missing_memory_raises_not_found(
        self, engine: MemoryEngine
    ) -> None:
        with pytest.raises(NotFoundError):
            engine.delete("missing-id")


# ----------------------------------------------------------------------
# archive / restore
# ----------------------------------------------------------------------


class TestArchiveRestore:
    def test_archive_transitions_and_keeps_indexes(self, engine: MemoryEngine) -> None:
        created = make_memory(engine)

        archived = engine.archive(created.memory_id)

        assert archived.state is LifecycleState.ARCHIVED
        assert archived.version == 2
        assert engine.metadata_store.get(created.memory_id).state is LifecycleState.ARCHIVED

        # Archived memories stay indexed with an updated state payload.
        assert vector_contains(engine, created.content, created.memory_id)
        payload = engine.vector_store._payloads[created.memory_id]  # type: ignore[attr-defined]
        assert payload["state"] == "archived"

        versions = engine.version_engine.list_versions(created.memory_id)
        assert versions[-1].change_type == "archive"
        assert versions[-1].diff["state"] == ["active", "archived"]

    def test_restore_returns_to_active(self, engine: MemoryEngine) -> None:
        created = make_memory(engine)
        engine.archive(created.memory_id)

        restored = engine.restore(created.memory_id)

        assert restored.state is LifecycleState.ACTIVE
        assert restored.version == 3
        payload = engine.vector_store._payloads[created.memory_id]  # type: ignore[attr-defined]
        assert payload["state"] == "active"

        versions = engine.version_engine.list_versions(created.memory_id)
        assert versions[-1].change_type == "restore"

    def test_restore_from_active_is_rejected(self, engine: MemoryEngine) -> None:
        created = make_memory(engine)
        with pytest.raises(ValidationError):
            engine.restore(created.memory_id)

    def test_archive_deleted_memory_is_rejected(self, engine: MemoryEngine) -> None:
        created = make_memory(engine)
        engine.delete(created.memory_id)
        with pytest.raises(ValidationError):
            engine.archive(created.memory_id)


# ----------------------------------------------------------------------
# permission
# ----------------------------------------------------------------------


class TestPermission:
    def test_private_memory_denies_foreign_read_and_write(
        self, engine: MemoryEngine
    ) -> None:
        created = make_memory(
            engine, owner_id="alice", permission=PermissionLevel.PRIVATE
        )

        with pytest.raises(PermissionDeniedError):
            engine.get(created.memory_id, principal_id="bob")
        with pytest.raises(PermissionDeniedError):
            engine.update(created.memory_id, principal_id="bob", content="x")
        with pytest.raises(PermissionDeniedError):
            engine.delete(created.memory_id, principal_id="bob")
        with pytest.raises(PermissionDeniedError):
            engine.archive(created.memory_id, principal_id="bob")

        # Owner and system principal pass.
        engine.get(created.memory_id, principal_id="alice")
        engine.get(created.memory_id, principal_id=SYSTEM_PRINCIPAL)

    def test_system_memory_readable_by_all_but_writable_only_by_system(
        self, engine: MemoryEngine
    ) -> None:
        created = make_memory(
            engine, owner_id="alice", permission=PermissionLevel.SYSTEM
        )

        # Any principal may read a SYSTEM memory.
        engine.get(created.memory_id, principal_id="bob")

        # Only the system principal may modify it — even its owner may not.
        with pytest.raises(PermissionDeniedError):
            engine.update(created.memory_id, principal_id="alice", content="x")
        engine.update(created.memory_id, principal_id=SYSTEM_PRINCIPAL, content="ok")

    def test_permission_failure_does_not_touch_access_stats(
        self, engine: MemoryEngine
    ) -> None:
        created = make_memory(engine, owner_id="alice")
        with pytest.raises(PermissionDeniedError):
            engine.get(created.memory_id, principal_id="bob")
        assert engine.metadata_store.get(created.memory_id).access_count == 0


# ----------------------------------------------------------------------
# list
# ----------------------------------------------------------------------


class TestList:
    def test_list_filters_by_owner_type_state_and_tags(
        self, engine: MemoryEngine
    ) -> None:
        alice_semantic = make_memory(
            engine,
            owner_id="alice",
            content="alice semantic",
            memory_type=MemoryType.SEMANTIC,
            tags=["work"],
        )
        alice_episodic = make_memory(
            engine,
            owner_id="alice",
            content="alice episodic",
            memory_type=MemoryType.EPISODIC,
            tags=["personal"],
        )
        bob_semantic = make_memory(
            engine,
            owner_id="bob",
            content="bob semantic",
            memory_type=MemoryType.SEMANTIC,
            tags=["work"],
        )

        assert {
            m.memory_id for m in engine.list_memories(owner_id="alice")
        } == {alice_semantic.memory_id, alice_episodic.memory_id}
        assert {
            m.memory_id for m in engine.list_memories(memory_type=MemoryType.SEMANTIC)
        } == {alice_semantic.memory_id, bob_semantic.memory_id}
        assert {
            m.memory_id for m in engine.list_memories(state=LifecycleState.ACTIVE)
        } == {
            alice_semantic.memory_id,
            alice_episodic.memory_id,
            bob_semantic.memory_id,
        }
        assert {
            m.memory_id for m in engine.list_memories(tags=["work"])
        } == {alice_semantic.memory_id, bob_semantic.memory_id}

    def test_list_respects_limit_and_offset(self, engine: MemoryEngine) -> None:
        for index in range(5):
            make_memory(engine, content=f"memory {index}")

        assert len(engine.list_memories(limit=2, offset=0)) == 2
        assert len(engine.list_memories(limit=2, offset=2)) == 2
        assert len(engine.list_memories(limit=2, offset=4)) == 1

    def test_list_applies_permission_filtering(self, engine: MemoryEngine) -> None:
        private_alice = make_memory(
            engine,
            owner_id="alice",
            content="private note",
            permission=PermissionLevel.PRIVATE,
        )
        system_mem = make_memory(
            engine,
            owner_id="kernel",
            content="system note",
            permission=PermissionLevel.SYSTEM,
        )

        as_alice = {m.memory_id for m in engine.list_memories(principal_id="alice")}
        assert as_alice == {private_alice.memory_id, system_mem.memory_id}

        as_bob = {m.memory_id for m in engine.list_memories(principal_id="bob")}
        assert as_bob == {system_mem.memory_id}


# ----------------------------------------------------------------------
# touch_access / reindex
# ----------------------------------------------------------------------


class TestTouchAndReindex:
    def test_touch_access_increments_and_persists(self, engine: MemoryEngine) -> None:
        created = make_memory(engine)

        touched = engine.touch_access(created)

        assert touched.access_count == 1
        assert touched.last_accessed_at is not None
        assert engine.metadata_store.get(created.memory_id).access_count == 1

    def test_reindex_upserts_vector_from_current_content(
        self, engine: MemoryEngine
    ) -> None:
        created = make_memory(engine, content="original")

        reindexed = engine.reindex(created.memory_id)

        assert reindexed.embedding == engine.embedder.embed("original")
        assert vector_contains(engine, "original", created.memory_id)
        assert engine.metadata_store.get(created.memory_id).embedding == reindexed.embedding

    def test_reindex_by_non_owner_raises_permission_denied(
        self, engine: MemoryEngine
    ) -> None:
        created = make_memory(
            engine,
            owner_id="alice",
            content="private reindex target",
            permission=PermissionLevel.PRIVATE,
        )

        with pytest.raises(PermissionDeniedError):
            engine.reindex(created.memory_id, principal_id="bob")

        # The owner and the system principal may reindex.
        engine.reindex(created.memory_id, principal_id="alice")
        engine.reindex(created.memory_id, principal_id=SYSTEM_PRINCIPAL)

    def test_reindex_missing_memory_raises_not_found(
        self, engine: MemoryEngine
    ) -> None:
        with pytest.raises(NotFoundError):
            engine.reindex("missing-id")
