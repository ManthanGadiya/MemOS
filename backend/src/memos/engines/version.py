"""Version Engine for MemOS.

The Version Engine owns the evolution of :class:`MemoryObject` entities. Per
``docs/SystemArchitecture.md`` (section 14) and ``docs/Algorithms.md``
(section 9), memories are never overwritten: every change produces an
immutable historical snapshot, version numbers increase monotonically, the
latest version is active, and a rollback creates a new version rather than
editing the past.

Each recorded snapshot is a :class:`MemoryVersion` that preserves:

- the identity (``memory_id``) and version number of the object,
- the content and user metadata at that point in time,
- the ``change_type`` that produced it,
- a field-level ``diff`` against the previous version when one is supplied.

The registry is per-instance in-memory state; the engine holds no global
state. The Memory Kernel coordinates all write operations through this
interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List

from memos.domain.exceptions import NotFoundError, ValidationError
from memos.domain.memory import (
    LifecycleState,
    MemoryObject,
    MemoryType,
    PermissionLevel,
    now_utc,
)


@dataclass
class MemoryVersion:
    """Snapshot of a Memory Object at one point in its history.

    ``version`` is the object's own version number at snapshot time; the
    engine never maintains a separate counter. ``metadata`` holds a copy of
    the object's user metadata together with a reserved ``_memos_snapshot``
    key that carries the remaining fields required for a faithful restore.
    ``diff`` describes field-level changes against the previous version
    (empty for the first version of a memory).

    Recorded versions are treated as history: the engine never edits a
    version once appended to a chain.
    """

    memory_id: str
    version: int
    content: str
    metadata: Dict[str, Any]
    created_at: datetime
    change_type: str
    diff: Dict[str, Any]


class VersionEngine:
    """In-memory version chain manager for MemOS.

    Each :meth:`record` appends one immutable snapshot to the chain belonging
    to ``MemoryObject.memory_id``. Chains grow monotonically by version; the
    engine validates that incoming versions strictly increase for an existing
    chain so the recorded history never regresses.
    """

    # Reserved key injected into MemoryVersion.metadata to carry the full
    # object state required for a faithful restore (everything except the
    # identity fields, which are preserved from the current object).
    _SNAPSHOT_KEY: str = "_memos_snapshot"

    # Change types recognized by the Version 1 lifecycle.
    _VALID_CHANGE_TYPES: frozenset[str] = frozenset(
        {"create", "update", "archive", "restore", "delete"}
    )

    # Object fields compared when producing a field-level diff (identity,
    # timestamps, counters, and embedding are intentionally excluded; the
    # user metadata is diffed separately by key).
    _DIFFABLE_FIELDS: tuple[str, ...] = (
        "content",
        "tags",
        "type",
        "permission",
        "state",
        "importance",
        "importance_category",
        "confidence",
    )

    def __init__(self) -> None:
        # memory_id -> version chain (oldest first by append order).
        self._registry: Dict[str, List[MemoryVersion]] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def record(
        self,
        memory: MemoryObject,
        change_type: str,
        previous: MemoryObject | None = None,
    ) -> MemoryVersion:
        """Record an immutable snapshot of ``memory`` and append it to the chain.

        The snapshot version equals ``memory.version``. When ``previous`` is
        supplied, the stored diff compares ``previous`` against ``memory``
        field by field; otherwise the diff is empty (this is the first
        version).

        :raises ValidationError: if ``change_type`` is unrecognized or the
            version would not strictly advance the memory's existing chain.
        """
        self._validate_change_type(change_type)
        self._ensure_monotonic(memory)

        diff: Dict[str, Any] = {}
        if previous is not None:
            diff = self._compute_diff(previous, memory)

        version_metadata = dict(memory.metadata)
        version_metadata[self._SNAPSHOT_KEY] = self._build_snapshot(memory)

        snapshot = MemoryVersion(
            memory_id=memory.memory_id,
            version=memory.version,
            content=memory.content,
            metadata=version_metadata,
            created_at=memory.updated_at,
            change_type=change_type,
            diff=diff,
        )
        self._registry.setdefault(memory.memory_id, []).append(snapshot)
        return snapshot

    def list_versions(self, memory_id: str) -> List[MemoryVersion]:
        """Return every version for ``memory_id``, oldest first.

        Returns an empty list when no version has been recorded.
        """
        return list(self._registry.get(memory_id, []))

    def get_version(self, memory_id: str, version: int) -> MemoryVersion:
        """Return the snapshot for ``memory_id`` at ``version``.

        :raises NotFoundError: if the memory is unknown or the version is
            absent from its chain.
        """
        chain = self._registry.get(memory_id)
        if chain is None:
            raise NotFoundError(f"No versions recorded for memory {memory_id!r}")
        for snapshot in chain:
            if snapshot.version == version:
                return snapshot
        raise NotFoundError(f"Version {version} not found for memory {memory_id!r}")

    def restore(self, memory: MemoryObject, version: int) -> MemoryObject:
        """Return a new :class:`MemoryObject` rolled back to ``version``.

        A rollback creates a *new* active version (``memory.version + 1``)
        whose content/tags/type/permission/metadata/state/importance/confidence
        match ``version``. Identity (``memory_id``, ``owner_id``) is preserved
        from the current object and ``updated_at`` is refreshed. The input
        ``memory`` is never mutated.

        :raises NotFoundError: if ``version`` is missing from the chain.
        """
        snapshot = self.get_version(memory.memory_id, version)

        # Copy the stored metadata before extracting the snapshot so the
        # historical record remains untouched.
        version_metadata = dict(snapshot.metadata)
        object_snapshot = version_metadata.pop(self._SNAPSHOT_KEY)

        return MemoryObject(
            content=object_snapshot["content"],
            memory_id=memory.memory_id,
            owner_id=memory.owner_id,
            type=MemoryType(object_snapshot["type"]),
            permission=PermissionLevel(object_snapshot["permission"]),
            tags=list(object_snapshot["tags"]),
            metadata=version_metadata,
            state=LifecycleState(object_snapshot["state"]),
            version=memory.version + 1,
            created_at=object_snapshot["created_at"],
            updated_at=now_utc(),
            last_accessed_at=object_snapshot["last_accessed_at"],
            access_count=object_snapshot["access_count"],
            importance=object_snapshot["importance"],
            importance_category=object_snapshot["importance_category"],
            confidence=object_snapshot["confidence"],
            # The embedding can no longer represent this content; it must be
            # regenerated so it always corresponds to the active version.
            embedding=None,
        )

    def clear(self) -> None:
        """Drop every recorded version chain."""
        self._registry.clear()

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _validate_change_type(self, change_type: str) -> None:
        """Reject unrecognized change types so history stays well-typed."""
        if change_type not in self._VALID_CHANGE_TYPES:
            raise ValidationError(
                f"Unknown change type {change_type!r}; "
                f"expected one of {sorted(self._VALID_CHANGE_TYPES)}"
            )

    def _ensure_monotonic(self, memory: MemoryObject) -> None:
        """Reject a version that does not strictly extend the existing chain."""
        chain = self._registry.get(memory.memory_id)
        if not chain:
            return
        latest_version = chain[-1].version
        if memory.version <= latest_version:
            raise ValidationError(
                f"Version {memory.version} does not extend the chain for memory "
                f"{memory.memory_id!r}, whose latest version is {latest_version}"
            )

    # ------------------------------------------------------------------
    # Diff & snapshot construction
    # ------------------------------------------------------------------

    def _compute_diff(
        self, previous: MemoryObject, current: MemoryObject
    ) -> Dict[str, Any]:
        """Return a field-level diff of ``current`` relative to ``previous``.

        Scalars and collections that differ are reported as ``[old, new]``
        pairs keyed by field name. Metadata keys are grouped into added /
        removed / changed entries. Enum fields are reported by their string
        value for a JSON-safe, explainable diff.
        """
        diff: Dict[str, Any] = {}
        for field_name in self._DIFFABLE_FIELDS:
            old_value = _to_serializable(getattr(previous, field_name))
            new_value = _to_serializable(getattr(current, field_name))
            if old_value != new_value:
                diff[field_name] = [old_value, new_value]
        metadata_changes = _metadata_diff(previous.metadata, current.metadata)
        if metadata_changes:
            diff["metadata"] = metadata_changes
        return diff

    def _build_snapshot(self, memory: MemoryObject) -> Dict[str, Any]:
        """Serialize the object state needed to reconstruct a restore."""
        return {
            "content": memory.content,
            "tags": list(memory.tags),
            "type": memory.type.value,
            "permission": memory.permission.value,
            "state": memory.state.value,
            "created_at": memory.created_at,
            "last_accessed_at": memory.last_accessed_at,
            "access_count": memory.access_count,
            "importance": memory.importance,
            "importance_category": memory.importance_category,
            "confidence": memory.confidence,
        }


def _to_serializable(value: Any) -> Any:
    """Render enum members as their string value for a JSON-safe diff."""
    return value.value if isinstance(value, Enum) else value


def _metadata_diff(
    previous: Dict[str, Any], current: Dict[str, Any]
) -> Dict[str, Any]:
    """Diff two metadata dicts into added / removed / changed key entries."""
    previous_keys = set(previous)
    current_keys = set(current)

    added = {key: current[key] for key in sorted(current_keys - previous_keys)}
    removed = {key: previous[key] for key in sorted(previous_keys - current_keys)}
    changed = {
        key: [previous[key], current[key]]
        for key in sorted(previous_keys & current_keys)
        if previous[key] != current[key]
    }

    result: Dict[str, Any] = {}
    if added:
        result["added"] = added
    if removed:
        result["removed"] = removed
    if changed:
        result["changed"] = changed
    return result


__all__ = ["MemoryVersion", "VersionEngine"]