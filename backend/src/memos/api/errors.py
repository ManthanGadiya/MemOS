"""Exception handlers for the MemOS REST API.

Kernel errors map 1:1 to HTTP status codes (SystemArchitecture.md REST API
chapter): ``PERMISSION_DENIED`` -> 403, ``INVALID_REQUEST`` -> 400,
``INTERNAL_ERROR`` -> 500. Pydantic validation failures and unhandled
exceptions normalize to the documented JSON envelope without leaking internal
details.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from memos.api import envelope
from memos.kernel.errors import KernelError, KernelErrorCode

# KernelErrorCode -> HTTP status (Security.md section 10, SRS section 13.7).
_KERNEL_ERROR_TO_HTTP: Dict[KernelErrorCode, int] = {
    KernelErrorCode.PERMISSION_DENIED: 403,
    KernelErrorCode.INVALID_REQUEST: 400,
    KernelErrorCode.INTERNAL_ERROR: 500,
}


def register_exception_handlers(app: FastAPI) -> None:
    """Attach the documented error handlers to ``app``."""

    @app.exception_handler(KernelError)
    async def _kernel_error_handler(request: Request, exc: KernelError) -> JSONResponse:
        status = _KERNEL_ERROR_TO_HTTP.get(exc.code, 500)
        return JSONResponse(
            status_code=status,
            content=envelope.error(
                getattr(request.state, "request_id", "") or "",
                exc.code.value,
                exc.message,
                details=exc.details,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=envelope.error(
                getattr(request.state, "request_id", "") or "",
                "INVALID_REQUEST",
                "request validation failed",
                details={"errors": exc.errors()},
            ),
        )

    @app.exception_handler(Exception)
    async def _internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
        # Never leak internal messages; the generic INTERNAL_ERROR envelope
        # carries only the request id.
        return JSONResponse(
            status_code=500,
            content=envelope.error(
                getattr(request.state, "request_id", "") or "",
                "INTERNAL_ERROR",
                "internal error",
                details={"request_id": getattr(request.state, "request_id", "") or None},
            ),
        )