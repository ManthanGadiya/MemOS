# REST API Layer — Implementation Plan

Status: reviewed, approved for implementation (2026-08-10)

## 1. Goal

Expose the Memory Kernel to external applications over HTTP. The REST API is a
presentation layer with **zero business logic** (SystemArchitecture.md §REST
API): it validates request models, forwards every call to the single
`MemoryKernel` instance, and maps results to the documented JSON envelope. The
API depends only on `memos.kernel`, pydantic models, and HTTP primitives —
engine imports are forbidden.

## 2. Endpoint surface

Base path `/api/v1`. All routes are defined in code exactly once; the docs
(tables in API.md and SRS §13.3) were reconciled to this set:

| Method | Path | Request body | Response `data` |
| --- | --- | --- | --- |
| POST | /memories | CreateMemoryRequest | memory |
| GET | /memories/{memory_id} | — | memory |
| PUT | /memories/{memory_id} | UpdateMemoryRequest | memory |
| DELETE | /memories/{memory_id} | — | memory |
| PUT | /memories/{memory_id}/archive | — | memory |
| PUT | /memories/{memory_id}/restore | — | memory |
| GET | /memories | query: type/owner/state/tags/limit/offset | list of memories |
| POST | /search | SearchRequest | list of scored results |
| GET | /memories/{memory_id}/relationships | — | list of relationships |
| POST | /memories/{memory_id}/relationships | AddRelationshipRequest | relationship |
| DELETE | /memories/{memory_id}/relationships/{relationship_id} | — | memory |
| GET | /memories/{memory_id}/versions | — | list of versions |
| GET | /memories/{memory_id}/versions/{version} | — | version |
| GET | /system/status | — | status info |
| GET | /health | — | health |
| GET | /dashboard/statistics | — | statistics |
| GET | /config | — | safe runtime config |

## 3. Module layout

```
backend/src/memos/api/
    __init__.py        # exports create_app
    app.py             # create_app(): FastAPI factory, lifespan, router wiring, middleware
    dependencies.py    # principal + request_id extraction, kernel dependency
    envelope.py        # success/error envelope builders
    errors.py          # KernelError -> HTTP handler; pydantic validation handler
    schemas.py         # pydantic request/response models
    routers/
        __init__.py
        memories.py
        search.py
        relationships.py
        versions.py
        system.py      # /health /system/status /dashboard/statistics /config
backend/tests/
    test_api.py
```

`create_app(kernel: MemoryKernel | None = None, settings: Settings | None = None)`
accepts an injected kernel so tests can use a disposable kernel on tmp stores;
when omitted, lifespan builds the kernel via `build_kernel(settings)` and
closes it on shutdown. The app instance is stateless; the kernel is stateful
(SystemArchitecture.md §REST API decision).

## 4. Response envelope

Every response carries `request_id`, `timestamp`, and `duration_ms`
(SRS §13.3: request identifier, timestamp, status, execution duration).

- Success: `{"success": true, "request_id", "timestamp", "duration_ms", "data", "metadata": {}}`
- Error:   `{"success": false, "request_id", "timestamp", "duration_ms", "error": {"code", "message", "details"}}`

`request_id`: honored from `X-Request-ID` header when present, else a new
uuid4. Echoed in the body and response header.

`principal_id` (the acting user): read from `X-Principal-ID` header, default
`"system"` (`SYSTEM_PRINCIPAL`). All kernel calls pass this through — matching
kernel semantics (ownerless/PRIVATE memories are read-only to others; system
may do everything).

## 5. Error mapping

Kernel emits exactly three codes (Security.md §10). The REST API maps 1:1 per
SystemArchitecture.md (HTTP: 400/403/404/409/428/500). Since the kernel
currently flattens `NotFoundError` to `INVALID_REQUEST` (400) and the docs list
404-NOT_FOUND as a real code, the API layer enriches the mapping by inspecting
the *original* exception where available:

| KernelError code | HTTP |
| --- | --- |
| PERMISSION_DENIED | 403 |
| INVALID_REQUEST | 400 |
| INTERNAL_ERROR | 500 |

Design decision (flagged in handoff, not silently changed): the kernel maps
`NotFoundError -> INVALID_REQUEST` (400). To honor SRS §13.7 (404-NOT_FOUND),
the API inspects the underlying exception: FastAPI handlers catch `KernelError`
and check `isinstance(original, NotFoundError)` is not available (kernel already
converted it) — so in V1 the API returns 400 INVALID_REQUEST for missing
memories, matching kernel behavior. A follow-up kernel change (preserve source
code in `KernelError.details`) can upgrade to 404 without API changes. The API
mapping table lives in one function so that upgrade is a one-line change.

Pydantic `RequestValidationError` -> 400 INVALID_REQUEST with field details.
Unhandled exceptions -> 500 INTERNAL_ERROR, no internal detail leak.

## 6. Implementation checklist

1. `pip install -e ".[api]"` in backend (adds fastapi + uvicorn).
2. Kernel additions (thin, permission-checked):
   - `list_versions(memory_id, principal_id)` and
     `get_version(memory_id, version, principal_id)` — route through
     VersionEngine, guarded by a READ permission check on the memory.
   - `statistics()` — counts from the metadata store (no per-principal data).
   - `health()` — liveness of stores + kernel, machine-readable.
3. `memos/api/` package per module layout.
4. Schemas: CreateMemoryRequest (content required; optional type/title/source/
   summary/tags/metadata/namespace/owner/permission), UpdateMemoryRequest
   (partial fields), SearchRequest (query required; top_k/add filters),
   AddRelationshipRequest, response models, envelope models.
5. Routers call kernel only; no engine imports.
6. Tests in `backend/tests/test_api.py` using `httpx`/TestClient:
   - CRUD happy path + archive/restore lifecycle,
   - search returns scored results,
   - relationships add/list/remove,
   - versions list/get,
   - health/status/statistics/config,
   - envelope shape (success + error), request_id echo, duration present,
   - permission denial -> 403 PERMISSION_DENIED; bad payload -> 400;
     missing memory -> 400 INVALID_REQUEST and no leak for internal errors.
7. Full suite green; docs (API.md) and README Current Status updated; commit.