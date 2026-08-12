"""Error mapping between the Memory Kernel and the MCP vocabulary.

``docs/MCP.md`` section 8 defines five structured error codes that every tool
returns. The kernel exposes its own five-code taxonomy (``Security.md``
section 10); this module maps one to the other and builds the deterministic
result envelope every tool returns.

Tools never raise across the protocol boundary: every outcome is a
``{"success": bool, ...}`` payload that the MCP client can inspect
deterministically (MCP.md section 11: all responses are deterministic).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, TypeVar

from memos.kernel.errors import KernelError, KernelErrorCode

T = TypeVar("T")

# KernelErrorCode -> MCP error code (MCP.md section 8).
_KERNEL_TO_MCP: Dict[KernelErrorCode, str] = {
    KernelErrorCode.INVALID_REQUEST: "INVALID_INPUT",
    KernelErrorCode.NOT_FOUND: "MEMORY_NOT_FOUND",
    KernelErrorCode.STORAGE_FAILURE: "STORAGE_FAILURE",
    KernelErrorCode.PERMISSION_DENIED: "PERMISSION_DENIED",
    KernelErrorCode.INTERNAL_ERROR: "INTERNAL_ERROR",
}


def to_mcp_code(code: KernelErrorCode) -> str:
    """Translate a kernel error code to the documented MCP error code."""
    return _KERNEL_TO_MCP.get(code, "INTERNAL_ERROR")


def success(data: Any) -> Dict[str, Any]:
    """Build a successful tool result."""
    return {"success": True, "data": data}


def error(code: str, message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build a failed tool result using the MCP error vocabulary."""
    return {
        "success": False,
        "error": {"code": code, "message": message, "details": details or {}},
    }


def call_kernel(operation: Callable[[], T]) -> Dict[str, Any]:
    """Run one kernel operation and wrap its outcome in the result envelope.

    Catches ``KernelError`` (the kernel's structured taxonomy) and maps it to
    the MCP vocabulary. Any unexpected exception becomes a generic
    ``INTERNAL_ERROR`` so internal details never leak to clients.
    """
    try:
        return success(operation())
    except KernelError as exc:
        return error(to_mcp_code(exc.code), exc.message, exc.details or {})
    except (ValueError, TypeError) as exc:
        # Argument coercion failures (invalid enums, malformed input) are
        # client errors, not internal failures.
        return error("INVALID_INPUT", str(exc))
    except Exception:  # noqa: BLE001 - never leak internal details
        return error("INTERNAL_ERROR", "internal error")


__all__ = ["success", "error", "call_kernel", "to_mcp_code"]