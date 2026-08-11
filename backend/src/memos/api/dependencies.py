"""Request-scoped dependencies for the MemOS REST API.

Every handler depends on a :class:`RequestContext` that bundles the single
kernel instance, the acting principal, the request id, and the envelope
helpers. The app is stateless with respect to the kernel; the kernel lives on
``app.state`` so it is shared by every request and by the MCP server.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi import Request

from memos.api import envelope
from memos.engines.permission import SYSTEM_PRINCIPAL
from memos.kernel.kernel import MemoryKernel

HEADER_PRINCIPAL = "X-Principal-ID"
HEADER_REQUEST_ID = "X-Request-ID"


@dataclass
class RequestContext:
    """Everything a handler needs: kernel, identity, and envelope helpers."""

    request: Request
    kernel: MemoryKernel
    principal_id: str
    request_id: str
    started_at: float

    def duration_ms(self) -> float:
        return (time.perf_counter() - self.started_at) * 1000.0

    def success(
        self,
        data: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return envelope.success(
            self.request_id,
            data,
            metadata=metadata,
            duration_ms=self.duration_ms(),
        )

    def error(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        return envelope.error(
            self.request_id,
            code,
            message,
            details=details,
            duration_ms=self.duration_ms(),
        )


def get_kernel(request: Request) -> MemoryKernel:
    """Return the kernel instance stored on the application state."""
    kernel: Optional[MemoryKernel] = getattr(request.app.state, "kernel", None)
    if kernel is None:
        raise RuntimeError("kernel not initialized; lifespan did not run")
    return kernel


def get_request_context(request: Request) -> RequestContext:
    """Compose the request-scoped context for handler dependencies."""
    started_at: float = getattr(request.state, "started_at", time.perf_counter())
    request_id: str = getattr(request.state, "request_id", "")
    if not request_id:
        request_id = request.headers.get(HEADER_REQUEST_ID, "")
    principal_id: str = request.headers.get(HEADER_PRINCIPAL, SYSTEM_PRINCIPAL)
    return RequestContext(
        request=request,
        kernel=get_kernel(request),
        principal_id=principal_id,
        request_id=request_id,
        started_at=started_at,
    )