"""Kernel-level request validation.

The Memory Kernel is the first line of validation (SRS section 10.20 and
section 15): malformed requests are rejected here, before any engine or
store is touched. Engines keep their own defence-in-depth checks; the kernel
validates the *shape* of every request, not business algorithms.

Failures raise :class:`~memos.domain.exceptions.ValidationError`, which the
kernel maps to ``INVALID_REQUEST`` (:mod:`memos.kernel.errors`).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from memos.config.settings import Settings
from memos.domain.exceptions import ValidationError
from memos.domain.memory import MemoryType, PermissionLevel

MAX_TAGS: int = 100
MAX_METADATA_KEYS: int = 500


class RequestValidator:
    """Validates the shape of kernel requests.

    Holds no mutable state; the injected :class:`Settings` supplies defaults
    (for example the default permission level).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # ------------------------------------------------------------------
    # Identifiers and principals
    # ------------------------------------------------------------------
    def validate_memory_id(self, memory_id: str) -> str:
        if not isinstance(memory_id, str) or not memory_id.strip():
            raise ValidationError("memory_id must be a non-empty string")
        return memory_id

    def validate_principal(self, principal_id: str) -> str:
        if not isinstance(principal_id, str) or not principal_id.strip():
            raise ValidationError("principal_id must be a non-empty string")
        return principal_id

    def validate_owner_id(self, owner_id: str) -> str:
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise ValidationError("owner_id must be a non-empty string")
        return owner_id

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------
    def validate_create(
        self,
        content: str,
        owner_id: str,
        memory_type: MemoryType,
        permission: Optional[PermissionLevel],
        tags: Optional[List[str]],
        metadata: Optional[Dict[str, Any]],
    ) -> None:
        self.validate_content(content)
        self.validate_owner_id(owner_id)
        if not isinstance(memory_type, MemoryType):
            raise ValidationError(f"invalid memory type: {memory_type!r}")
        if permission is not None and not isinstance(permission, PermissionLevel):
            raise ValidationError(f"invalid permission level: {permission!r}")
        if tags is not None:
            self.validate_tags(tags)
        if metadata is not None:
            self.validate_metadata(metadata)

    def validate_content(self, content: str) -> str:
        normalized = content.strip() if isinstance(content, str) else ""
        if not normalized:
            raise ValidationError("memory content must not be empty")
        return normalized

    def validate_tags(self, tags: List[str]) -> None:
        if not isinstance(tags, list) or not all(isinstance(t, str) and t.strip() for t in tags):
            raise ValidationError("tags must be a list of non-empty strings")
        if len(tags) > MAX_TAGS:
            raise ValidationError(f"tags must not exceed {MAX_TAGS} entries")

    def validate_metadata(self, metadata: Dict[str, Any]) -> None:
        if not isinstance(metadata, dict):
            raise ValidationError("metadata must be a mapping")
        if len(metadata) > MAX_METADATA_KEYS:
            raise ValidationError(f"metadata must not exceed {MAX_METADATA_KEYS} keys")

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------
    def validate_update(self, memory_id: str, fields: Dict[str, Any]) -> None:
        self.validate_memory_id(memory_id)
        if not fields:
            raise ValidationError("update provides no fields to change")
        content = fields.get("content")
        if content is not None:
            self.validate_content(content)
        tags = fields.get("tags")
        if tags is not None:
            self.validate_tags(tags)
        metadata = fields.get("metadata")
        if metadata is not None:
            self.validate_metadata(metadata)

    # ------------------------------------------------------------------
    # Search / retrieval
    # ------------------------------------------------------------------
    def validate_search(
        self,
        query: str,
        top_k: Optional[int],
        tags: Optional[List[str]],
    ) -> None:
        if isinstance(query, str) and query.strip():
            pass
        else:
            raise ValidationError("search query must be a non-empty string")
        if top_k is not None and (not isinstance(top_k, int) or top_k <= 0):
            raise ValidationError("top_k must be a positive integer")
        if tags is not None:
            self.validate_tags(tags)

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------
    def validate_relationship(
        self,
        source_id: str,
        target_id: str,
        weight: float,
    ) -> None:
        self.validate_memory_id(source_id)
        self.validate_memory_id(target_id)
        if not isinstance(weight, (int, float)) or not 0.0 <= float(weight) <= 1.0:
            raise ValidationError("relationship weight must be in [0, 1]")

    # ------------------------------------------------------------------
    # Permission resolution
    # ------------------------------------------------------------------
    def resolve_permission(
        self, permission: Optional[PermissionLevel], default: Optional[str] = None
    ) -> PermissionLevel:
        """Resolve an explicit permission to a :class:`PermissionLevel`.

        When ``permission`` is omitted, the documented default is applied
        (from ``settings.default_permission`` unless overridden).
        """
        if permission is not None:
            return permission
        source = default or self._settings.default_permission
        try:
            return PermissionLevel(source)
        except ValueError:
            raise ValidationError(f"invalid permission level: {source!r}") from None