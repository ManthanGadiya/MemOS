"""Permission Engine for MemOS.

The Permission Engine is the sole authority for authorization decisions in
MemOS. Per ``docs/Security.md`` and ``docs/SystemArchitecture.md``, every
memory operation must pass through this engine before reaching any Core
Service. The engine implements the Version 1 permission model, which
recognizes two visibility levels:

- ``PRIVATE``: readable/writable only by the owning principal.
- ``SYSTEM``:  infrastructure memory that any principal may read, but only
  the ``system`` principal may modify.

The ``system`` principal is a kernel-level identity that bypasses every
check (used for infrastructure operations). The engine holds no mutable
state; all decisions are deterministic functions of the memory metadata and
the requesting principal.
"""

from __future__ import annotations

from typing import List

from memos.config.settings import Settings
from memos.domain.exceptions import PermissionDeniedError
from memos.domain.memory import MemoryObject, PermissionLevel

# Kernel-level identity granted unfettered access. Exposed as a module
# constant (not mutable state) so the Memory Kernel and the engine agree on
# the reserved name.
SYSTEM_PRINCIPAL: str = "system"


class PermissionEngine:
    """Decides whether a principal may read or modify a Memory Object.

    The engine depends only on an immutable :class:`Settings` object and holds
    no runtime state, which keeps it deterministic and trivially testable.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # ------------------------------------------------------------------
    # Public interface -- read authorization
    # ------------------------------------------------------------------
    def can_access(self, memory: MemoryObject, principal_id: str) -> bool:
        """Return whether ``principal_id`` is allowed to read ``memory``.

        Rules per docs/Security.md:

        - The ``system`` principal bypasses all checks.
        - ``SYSTEM`` memories are readable by any principal.
        - ``PRIVATE`` memories are readable only by their owner, or by any
          principal when the memory has no registered owner.
        """
        if self._is_system_principal(principal_id):
            return True
        if memory.permission is PermissionLevel.SYSTEM:
            return True
        return self._is_private_read_allowed(memory, principal_id)

    def require_access(self, memory: MemoryObject, principal_id: str) -> None:
        """Raise :class:`PermissionDeniedError` if reading is not allowed."""
        if not self.can_access(memory, principal_id):
            raise PermissionDeniedError(
                "Principal not authorized to read this memory.",
                {
                    "memory_id": memory.memory_id,
                    "permission": memory.permission.value,
                    "principal_id": principal_id,
                },
            )

    # ------------------------------------------------------------------
    # Public helpers -- write authorization
    # ------------------------------------------------------------------

    def can_modify(self, memory: MemoryObject, principal_id: str) -> bool:
        """Return whether ``principal_id`` is allowed to modify ``memory``.

        Only the owner may modify a memory. ``SYSTEM`` memories may only be
        modified by the ``system`` principal; ``PRIVATE`` memories only by
        their owner.
        """
        if self._is_system_principal(principal_id):
            return True
        if memory.permission is PermissionLevel.SYSTEM:
            # A SYSTEM memory belongs to the kernel; no ordinary principal
            # may modify it.
            return False
        return self._is_principal_owner(memory, principal_id)

    def require_modify(self, memory: MemoryObject, principal_id: str) -> None:
        """Raise :class:`PermissionDeniedError` if modification is barred."""
        if not self.can_modify(memory, principal_id):
            raise PermissionDeniedError(
                "Principal not authorized to modify this memory",
                {
                    "memory_id": memory.memory_id,
                    "permission": memory.permission.value,
                    "principal_id": principal_id,
                },
            )

    # ------------------------------------------------------------------
    # Batch helper ------------------------------------------------------
    # ------------------------------------------------------------------

    def filter_accessible(
        self, memories: List[MemoryObject], principal_id: str
    ) -> List[MemoryObject]:
        """Return only the memories in ``memories`` that are readable."""
        return [
            memory
            for memory in memories
            if self.can_access(memory, principal_id)
        ]

    # ------------------------------------------------------------------
    # Private decision helpers -----------------------------------------
    # ------------------------------------------------------------------

    @staticmethod
    def _is_system_principal(principal_id: str) -> bool:
        """Whether ``principal_id`` is the privileged kernel identity."""
        return principal_id == SYSTEM_PRINCIPAL

    @staticmethod
    def _is_principal_owner(memory: MemoryObject, principal_id: str) -> bool:
        """Whether ``principal_id`` matches the memory's owner."""
        return memory.owner_id == principal_id

    @staticmethod
    def _memory_has_owner(memory: MemoryObject) -> bool:
        """Whether the memory carries a non-empty owner identity."""
        return bool(memory.owner_id)

    def _is_private_read_allowed(
        self, memory: MemoryObject, principal_id: str
    ) -> bool:
        """Allow reading a PRIVATE memory for its owner or an ownerless one."""
        if not self._memory_has_owner(memory):
            return True
        return self._is_principal_owner(memory, principal_id)