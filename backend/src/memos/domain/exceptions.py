"""Domain exceptions shared across MemOS subsystems.

The Memory Kernel translates these into standard MemOS error responses
(``{"success": false, "error": {"code": ..., "message": ...}}``) at the
API/MCP boundary.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class MemOSError(Exception):
    """Base class for all MemOS domain errors."""

    code = "memos_error"
    http_status = 400

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            },
        }


class ValidationError(MemOSError):
    code = "validation_error"


class NotFoundError(MemOSError):
    code = "not_found"
    http_status = 404


class PermissionDeniedError(MemOSError):
    code = "permission_denied"
    http_status = 403


class LifecycleTransitionError(MemOSError):
    code = "invalid_lifecycle_transition"


class ImmutabilityError(MemOSError):
    code = "immutability_violation"


class StorageError(MemOSError):
    code = "storage_error"
    http_status = 500


class TransactionError(MemOSError):
    code = "transaction_error"


class EmbeddingError(MemOSError):
    code = "embedding_error"


class ConfigurationError(MemOSError):
    code = "configuration_error"
    http_status = 500