"""Structured error taxonomy for the Memory Kernel.

Security.md section 10 defines a fixed set of structured error codes exposed
to clients:

- ``PERMISSION_DENIED`` — unauthorized operation
- ``INVALID_REQUEST`` — invalid input
- ``INTERNAL_ERROR`` — unexpected failure

Sensitive internal details must never be exposed to clients, so any un-mapped
exception becomes a generic ``INTERNAL_ERROR`` whose ``details`` carry only
safe, request-scoped context (request id and operation).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

from memos.domain.exceptions import (
    ConfigurationError,
    EmbeddingError,
    ImmutabilityError,
    LifecycleTransitionError,
    MemOSError,
    NotFoundError,
    PermissionDeniedError,
    StorageError,
    TransactionError,
    ValidationError,
)


class KernelErrorCode(str, Enum):
    """The three structured error codes a kernel caller may receive."""

    PERMISSION_DENIED = "PERMISSION_DENIED"
    INVALID_REQUEST = "INVALID_REQUEST"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# Request-scoped keys that are always safe to surface (never tracebacks, never
# store internals, never exception messages for INTERNAL_ERROR).
_SAFE_DETAIL_KEYS: tuple[str, ...] = ("request_id", "operation")


class KernelError(Exception):
    """A structured error raised by the Memory Kernel.

    ``details`` is always JSON-safe and, for :attr:`KernelErrorCode.INTERNAL_ERROR`,
    is restricted to the safe request-scoped keys in :data:`_SAFE_DETAIL_KEYS`.
    """

    def __init__(
        self,
        code: KernelErrorCode,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_response(self) -> Dict[str, Any]:
        """Render the error as a MemOS API response payload."""
        return {
            "success": False,
            "error": {
                "code": self.code.value,
                "message": self.message,
                "details": self.details,
            },
        }

    @classmethod
    def permission_denied(cls, message: str, request_id: Optional[str] = None) -> "KernelError":
        return cls(KernelErrorCode.PERMISSION_DENIED, message, {"request_id": request_id})

    @classmethod
    def invalid_request(cls, message: str, request_id: Optional[str] = None) -> "KernelError":
        return cls(KernelErrorCode.INVALID_REQUEST, message, {"request_id": request_id})

    @classmethod
    def internal(cls, request_id: Optional[str] = None) -> "KernelError":
        return cls(
            KernelErrorCode.INTERNAL_ERROR,
            "internal error",
            {"request_id": request_id},
        )


_KNOWN_TO_CODE: dict[type[MemOSError], KernelErrorCode] = {
    ValidationError: KernelErrorCode.INVALID_REQUEST,
    NotFoundError: KernelErrorCode.INVALID_REQUEST,
    LifecycleTransitionError: KernelErrorCode.INVALID_REQUEST,
    ImmutabilityError: KernelErrorCode.INVALID_REQUEST,
    PermissionDeniedError: KernelErrorCode.PERMISSION_DENIED,
    StorageError: KernelErrorCode.INTERNAL_ERROR,
    TransactionError: KernelErrorCode.INTERNAL_ERROR,
    EmbeddingError: KernelErrorCode.INTERNAL_ERROR,
    ConfigurationError: KernelErrorCode.INTERNAL_ERROR,
}


def to_kernel_error(error: Exception, request_id: Optional[str] = None) -> KernelError:
    """Translate an arbitrary exception into a :class:`KernelError`.

    Known :class:`MemOSError` subclasses map to their documented code while
    preserving their message and safe details. Any other exception (including
    a raw ``RuntimeError`` or ``ValueError`` raised inside an engine or store)
    maps to a generic ``INTERNAL_ERROR`` so internals never leak.
    """
    if isinstance(error, MemOSError):
        code = _KNOWN_TO_CODE.get(type(error), KernelErrorCode.INTERNAL_ERROR)
        if code is KernelErrorCode.INTERNAL_ERROR:
            # Recognized exception type but mapped internal: keep message
            # (it originates from MemOS, not a host traceback), only scrub
            # non-logging details for internal codes.
            safe_details = {k: v for k, v in error.details.items() if k in _SAFE_DETAIL_KEYS}
            return KernelError(code, error.message, safe_details or {"request_id": request_id})
        return KernelError(code, error.message, {**({"request_id": request_id} if request_id else {}), **error.details})
    return KernelError.internal(request_id)