"""Tests for the MemOS Permission Engine.

Covers the Version 1 permission model from docs/Security.md:
- PRIVATE memories are readable/writable only by their owner.
- SYSTEM memories are readable by any principal but modifiable only by the
  ``system`` principal.
- The ``system`` principal bypasses all checks.
- Ownerless memories are readable by any principal.
"""

from typing import List

import pytest

from memos.config.settings import Settings
from memos.domain.exceptions import PermissionDeniedError
from memos.domain.memory import MemoryObject, PermissionLevel
from memos.engines import PermissionEngine, SYSTEM_PRINCIPAL

OWNER_ID: str = "alice"
OTHER_PRINCIPAL: str = "bob"


@pytest.fixture
def engine() -> PermissionEngine:
    """A permission engine backed by the default settings."""
    return PermissionEngine(settings=Settings())


@pytest.fixture
def private_memory() -> MemoryObject:
    """A PRIVATE memory owned by ``OWNER_ID``."""
    return MemoryObject(content="private note", owner_id=OWNER_ID)


@pytest.fixture
def system_memory() -> MemoryObject:
    """A SYSTEM-level infrastructure memory."""
    return MemoryObject(
        content="system bootstrap state",
        owner_id=SYSTEM_PRINCIPAL,
        permission=PermissionLevel.SYSTEM,
    )


# ----------------------------------------------------------------------
# can_access
# ----------------------------------------------------------------------

class TestCanAccess:
    def test_owner_can_access_own_private_memory(
        self, engine: PermissionEngine, private_memory: MemoryObject
    ) -> None:
        assert engine.can_access(private_memory, OWNER_ID) is True

    def test_non_owner_denied_private_memory(
        self, engine: PermissionEngine, private_memory: MemoryObject
    ) -> None:
        assert engine.can_access(private_memory, OTHER_PRINCIPAL) is False

    def test_any_principal_reads_system_memory(
        self, engine: PermissionEngine, system_memory: MemoryObject
    ) -> None:
        assert engine.can_access(system_memory, OWNER_ID) is True
        assert engine.can_access(system_memory, OTHER_PRINCIPAL) is True

    def test_ownerless_private_memory_readable_by_anyone(
        self, engine: PermissionEngine
    ) -> None:
        ownerless = MemoryObject(content="shared scratch", owner_id="")
        assert engine.can_access(ownerless, OTHER_PRINCIPAL) is True

    def test_system_principal_bypasses_all_access_checks(
        self, engine: PermissionEngine, private_memory: MemoryObject
    ) -> None:
        assert engine.can_access(private_memory, SYSTEM_PRINCIPAL) is True


# ----------------------------------------------------------------------
# require_access
# ----------------------------------------------------------------------

class TestRequireAccess:
    def test_require_access_allows_authorized_read(
        self, engine: PermissionEngine, private_memory: MemoryObject
    ) -> None:
        engine.require_access(private_memory, OWNER_ID)  # must not raise

    def test_require_access_raises_permission_denied(
        self, engine: PermissionEngine, private_memory: MemoryObject
    ) -> None:
        with pytest.raises(PermissionDeniedError):
            engine.require_access(private_memory, OTHER_PRINCIPAL)


# ----------------------------------------------------------------------
# can_modify
# ----------------------------------------------------------------------

class TestCanModify:
    def test_owner_can_modify_private_memory(
        self, engine: PermissionEngine, private_memory: MemoryObject
    ) -> None:
        assert engine.can_modify(private_memory, OWNER_ID) is True

    def test_non_owner_cannot_modify_private_memory(
        self, engine: PermissionEngine, private_memory: MemoryObject
    ) -> None:
        assert engine.can_modify(private_memory, OTHER_PRINCIPAL) is False

    def test_ordinary_principal_cannot_modify_system_memory(
        self, engine: PermissionEngine, system_memory: MemoryObject
    ) -> None:
        assert engine.can_modify(system_memory, OTHER_PRINCIPAL) is False

    def test_system_principal_can_modify_system_memory(
        self, engine: PermissionEngine, system_memory: MemoryObject
    ) -> None:
        assert engine.can_modify(system_memory, SYSTEM_PRINCIPAL) is True


# ----------------------------------------------------------------------
# require_modify
# ----------------------------------------------------------------------

class TestRequireModify:
    def test_require_modify_allows_authorized_write(
        self, engine: PermissionEngine, private_memory: MemoryObject
    ) -> None:
        engine.require_modify(private_memory, OWNER_ID)  # must not raise

    def test_require_modify_raises_permission_denied(
        self, engine: PermissionEngine, private_memory: MemoryObject
    ) -> None:
        with pytest.raises(PermissionDeniedError):
            engine.require_modify(private_memory, OTHER_PRINCIPAL)

    def test_require_modify_denies_ordinary_principal_on_system_memory(
        self, engine: PermissionEngine, system_memory: MemoryObject
    ) -> None:
        with pytest.raises(PermissionDeniedError):
            engine.require_modify(system_memory, OTHER_PRINCIPAL)


# ----------------------------------------------------------------------
# filter_accessible
# ----------------------------------------------------------------------

class TestFilterAccessible:
    def test_filters_to_only_accessible_memories(
        self,
        engine: PermissionEngine,
        private_memory: MemoryObject,
        system_memory: MemoryObject,
    ) -> None:
        foreign_private = MemoryObject(
            content="bob's secret", owner_id=OTHER_PRINCIPAL
        )
        memories: List[MemoryObject] = [
            private_memory,
            system_memory,
            foreign_private,
        ]

        visible = engine.filter_accessible(memories, OWNER_ID)

        assert private_memory in visible
        assert system_memory in visible
        assert foreign_private not in visible

    def test_filter_accessible_empty_input(
        self, engine: PermissionEngine
    ) -> None:
        assert engine.filter_accessible([], OWNER_ID) == []
