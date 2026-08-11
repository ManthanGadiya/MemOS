"""Application factory for the MemOS REST API.

``create_app`` assembles a stateless FastAPI application that owns exactly one
kernel instance. The kernel is constructed during lifespan startup (via the
single ``build_kernel`` factory), shared by every request through
``app.state.kernel``, and closed on shutdown. A pre-built kernel can be
injected for the integration test suite.

The request middleware stamps the start time and request id on every request so
that handlers and error handlers can build the documented envelope
(SRS 13.3). The router tree is mounted under ``/api/v1``.
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request

from memos.api.errors import register_exception_handlers
from memos.api.routers import api_router
from memos.config.settings import Settings
from memos.kernel.factory import build_kernel
from memos.kernel.kernel import MemoryKernel

HEADER_REQUEST_ID = "X-Request-ID"


def create_app(
    kernel: Optional[MemoryKernel] = None,
    settings: Optional[Settings] = None,
) -> FastAPI:
    """Create the MemOS REST API application.

    Args:
        kernel: Optional pre-built kernel. When ``None``, the lifespan builds
            one from ``settings`` using :func:`build_kernel`.
        settings: Optional runtime configuration. When ``None`` a default
            :class:`Settings` is built (honouring ``MEMOS_`` env vars).

    Returns:
        A configured FastAPI application.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        instance = kernel if kernel is not None else build_kernel(settings)
        app.state.kernel = instance
        try:
            yield
        finally:
            instance.close()

    configured = settings if settings is not None else Settings()
    app = FastAPI(
        title=configured.app_name,
        version=configured.version,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def stamp_request(request: Request, call_next):
        request.state.started_at = time.perf_counter()
        request_id = request.headers.get(HEADER_REQUEST_ID) or uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[HEADER_REQUEST_ID] = request_id
        return response

    register_exception_handlers(app)
    app.include_router(api_router)
    return app


__all__ = ["create_app"]