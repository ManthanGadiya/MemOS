"""Tests for the MemOS Version Engine.

Covers the Version 1 versioning rules from docs/Algorithms.md (section 9)
and docs/SystemArchitecture.md (section 14):
- version numbers match the Memory Object and increase monotonically,
- recorded history is never edited,
- rollback produces a new active version without mutating the input,
- missing versions raise NotFoundError.
"""

import pytest

from memos.domain.exceptions import NotFoundError, ValidationError
from memos.domain.memory import LifecycleState, MemoryObject, MemoryType
from memos.engines import MemoryVersion, VersionEngine


@pytest.fixture
def engine() -> VersionEngine:
    """An isolated, empty version registry."""
    return VersionEngine()


def make_memory(**overrides: object) -> MemoryObject:
    """Build a Memory Object from defaults plus explicit overrides."""
    defaults: dict[str, object] = {
        "content": "alpha",
        "owner_id": "alice",
        "tags": ["work"],
        "metadata": {"source": "user"},
        "importance": 0.7,
        "confidence": 0.6,
    }
    defaults.update(overrides)
    return MemoryObject(**defaults)


# ----------------------------------------------------------------------
# record
# ----------------------------------------------------------------------


class TestRecord:
    def test_record_creates_snapshot_with_correct_version(
        self, engine: VersionEngine
    ) -> None:
        created = make_memory(content="first")

        first = engine.record(created, change_type="create")

        assert isinstance(first, MemoryVersion)
        assert first.version == created.version == 1
        assert first.memory_id == created.memory_id
        assert first.content == "first"
        assert first.change_type == "create"
        assert first.created_at == created.updated_at
        # No previous version exists, so there is nothing to diff against.
        assert first.diff == {}

        updated = make_memory(
            content="second", memory_id=created.memory_id, version=2
        )
        second = engine.record(updated, change_type="update", previous=created)

        assert second.version == updated.version == 2
        assert second.memory_id == created.memory_id
        assert second.change_type == "update"
        assert second.diff["content"] == ["first", "second"]

    def test_record_stores_user_metadata_in_snapshot(
        self, engine: VersionEngine
    ) -> None:
        memory = make_memory(metadata={"source": "user", "n": 3})

        snapshot = engine.record(memory, change_type="create")

        # The user-facing metadata survives inside the recorded snapshot.
        assert snapshot.metadata["source"] == "user"
        assert snapshot.metadata["n"] == 3

    def test_record_rejects_unknown_change_type(
        self, engine: VersionEngine
    ) -> None:
        with pytest.raises(ValidationError):
            engine.record(make_memory(), change_type="explode")

    def test_record_rejects_version_that_does_not_extend_chain(
        self, engine: VersionEngine
    ) -> None:
        created = make_memory()
        engine.record(created, change_type="create")

        duplicate = make_memory(
            content="again", memory_id=created.memory_id, version=1
        )
        with pytest.raises(ValidationError):
            engine.record(duplicate, change_type="update", previous=created)

    def test_record_keeps_chains_isolated_per_memory(
        self, engine: VersionEngine
    ) -> None:
        first_memory = make_memory(content="one")
        second_memory = make_memory(content="two")
        engine.record(first_memory, change_type="create")
        engine.record(second_memory, change_type="create")

        assert len(engine.list_versions(first_memory.memory_id)) == 1
        assert len(engine.list_versions(second_memory.memory_id)) == 1


# ----------------------------------------------------------------------
# list_versions
# ----------------------------------------------------------------------


class TestListVersions:
    def test_list_versions_returns_oldest_first(
        self, engine: VersionEngine
    ) -> None:
        first = make_memory(content="one")
        engine.record(first, change_type="create")
        second = make_memory(content="two", memory_id=first.memory_id, version=2)
        engine.record(second, change_type="update", previous=first)
        third = make_memory(content="three", memory_id=first.memory_id, version=3)
        engine.record(third, change_type="update", previous=second)

        versions = engine.list_versions(first.memory_id)

        assert [entry.version for entry in versions] == [1, 2, 3]
        assert [entry.content for entry in versions] == ["one", "two", "three"]

    def test_list_versions_empty_for_unknown_memory(
        self, engine: VersionEngine
    ) -> None:
        assert engine.list_versions("missing-id") == []

    def test_list_versions_returns_a_copy(
        self, engine: VersionEngine
    ) -> None:
        first = make_memory()
        engine.record(first, change_type="create")

        returned = engine.list_versions(first.memory_id)
        returned.append(MemoryVersion("x", 9, "y", {}, first.created_at, "x", {}))

        assert len(engine.list_versions(first.memory_id)) == 1


# ----------------------------------------------------------------------
# get_version
# ----------------------------------------------------------------------


class TestGetVersion:
    def test_get_version_returns_requested_version(
        self, engine: VersionEngine
    ) -> None:
        first = make_memory(content="one")
        engine.record(first, change_type="create")
        second = make_memory(content="two", memory_id=first.memory_id, version=2)
        engine.record(second, change_type="update", previous=first)

        assert engine.get_version(first.memory_id, 1).content == "one"
        assert engine.get_version(first.memory_id, 2).content == "two"

    def test_get_version_raises_not_found_for_unknown_memory(
        self, engine: VersionEngine
    ) -> None:
        with pytest.raises(NotFoundError):
            engine.get_version("missing-id", 1)

    def test_get_version_raises_not_found_for_missing_version(
        self, engine: VersionEngine
    ) -> None:
        first = make_memory()
        engine.record(first, change_type="create")

        with pytest.raises(NotFoundError):
            engine.get_version(first.memory_id, 99)


# ----------------------------------------------------------------------
# restore
# ----------------------------------------------------------------------


class TestRestore:
    def test_restore_increments_version_and_preserves_memory_id(
        self, engine: VersionEngine
    ) -> None:
        original = make_memory(
            content="original",
            tags=["work", "urgent"],
            metadata={"source": "user"},
            importance=0.9,
        )
        engine.record(original, change_type="create")
        current = make_memory(
            content="mutated",
            memory_id=original.memory_id,
            tags=["personal"],
            metadata={"source": "model"},
            importance=0.1,
            version=2,
        )
        engine.record(current, change_type="update", previous=original)

        restored = engine.restore(current, version=1)

        assert restored.memory_id == original.memory_id
        assert restored.version == current.version + 1 == 3
        assert restored.content == "original"
        assert restored.tags == ["work", "urgent"]
        assert restored.metadata == {"source": "user"}
        assert restored.importance == 0.9

    def test_restore_does_not_mutate_input(self, engine: VersionEngine) -> None:
        original = make_memory(content="original")
        engine.record(original, change_type="create")
        current = make_memory(
            content="mutated", memory_id=original.memory_id, version=2
        )
        engine.record(current, change_type="update", previous=original)

        engine.restore(current, version=1)

        assert current.content == "mutated"
        assert current.version == 2
        assert current.tags == ["work"]
        assert current.metadata == {"source": "user"}

    def test_restore_is_repeatable_and_preserves_history(
        self, engine: VersionEngine
    ) -> None:
        original = make_memory(content="original")
        engine.record(original, change_type="create")
        current = make_memory(
            content="mutated", memory_id=original.memory_id, version=2
        )
        engine.record(current, change_type="update", previous=original)

        first_restore = engine.restore(current, version=1)
        second_restore = engine.restore(current, version=1)

        assert first_restore.content == second_restore.content == "original"
        # The recorded history is unchanged by restore calls.
        assert [entry.version for entry in engine.list_versions(original.memory_id)] == [
            1,
            2,
        ]

    def test_restore_raises_not_found_for_missing_version(
        self, engine: VersionEngine
    ) -> None:
        current = make_memory()
        engine.record(current, change_type="create")

        with pytest.raises(NotFoundError):
            engine.restore(current, version=7)


# ----------------------------------------------------------------------
# diff
# ----------------------------------------------------------------------


class TestDiff:
    def test_diff_captures_content_change(self, engine: VersionEngine) -> None:
        previous = make_memory(content="before", tags=["a"], metadata={"k": 1})
        current = make_memory(
            content="after",
            memory_id=previous.memory_id,
            tags=["a", "b"],
            metadata={"k": 2, "extra": True},
            importance=0.8,
            version=2,
        )

        snapshot = engine.record(current, change_type="update", previous=previous)

        assert snapshot.diff["content"] == ["before", "after"]
        assert snapshot.diff["tags"] == [["a"], ["a", "b"]]
        assert snapshot.diff["importance"] == [0.7, 0.8]

    def test_diff_captures_metadata_added_removed_changed(
        self, engine: VersionEngine
    ) -> None:
        previous = make_memory(content="stable", metadata={"keep": 1, "drop": "bye"})
        current = make_memory(
            content="stable",
            memory_id=previous.memory_id,
            metadata={"keep": 2, "new": True},
            version=2,
        )

        snapshot = engine.record(current, change_type="update", previous=previous)

        # Content is identical, so the diff contains only metadata changes.
        assert "content" not in snapshot.diff
        assert snapshot.diff["metadata"] == {
            "changed": {"keep": [1, 2]},
            "removed": {"drop": "bye"},
            "added": {"new": True},
        }

    def test_diff_reports_enum_fields_by_value(self, engine: VersionEngine) -> None:
        previous = make_memory(content="x")
        current = make_memory(
            content="x",
            memory_id=previous.memory_id,
            state=LifecycleState.ARCHIVED,
            type=MemoryType.SEMANTIC,
            version=2,
        )

        snapshot = engine.record(current, change_type="archive", previous=previous)

        assert snapshot.diff["state"] == ["active", "archived"]
        assert snapshot.diff["type"] == ["general", "semantic"]


# ----------------------------------------------------------------------
# clear
# ----------------------------------------------------------------------


class TestClear:
    def test_clear_empties_registry(self, engine: VersionEngine) -> None:
        first = make_memory(content="one")
        second = make_memory(content="two")
        engine.record(first, change_type="create")
        engine.record(second, change_type="create")

        engine.clear()

        assert engine.list_versions(first.memory_id) == []
        assert engine.list_versions(second.memory_id) == []
        with pytest.raises(NotFoundError):
            engine.get_version(first.memory_id, 1)
