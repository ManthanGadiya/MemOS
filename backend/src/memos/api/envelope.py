"""JSON envelopes for every MemOS API response.

SRS section 13.3 fixes the response shape: every response carries a request
identifier, timestamp, status, and execution duration. Success responses wrap
``data`` and optional ``metadata``; error responses carry a structured
``error`` object with a documented code, message, and safe details.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def success(
    request_id: str,
    data: Any,
    metadata: Optional[Dict[str, Any]] = None,
    duration_ms: Optional[float] = None,
) -> Dict[str, Any]:
    """Build a success envelope with the documented shape."""
    return {
        "success": True,
        "request_id": request_id,
        "timestamp": _now_iso(),
        "duration_ms": duration_ms,
        "data": data,
        "metadata": metadata or {},
    }


def error(
    request_id: str,
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    duration_ms: Optional[float] = None,
) -> Dict[str, Any]:
    """Build an error envelope with the documented shape."""
    return {
        "success": False,
        "request_id": request_id,
        "timestamp": _now_iso(),
        "duration_ms": duration_ms,
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        },
    }