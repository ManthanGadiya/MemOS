# MCP Server — Implementation Plan

Status: implemented (2026-08-12) — kernel taxonomy extended (NOT_FOUND, STORAGE_FAILURE); MCP layer complete; all 229 tests pass

## 1. Goal

Expose the Memory Kernel to MCP-compatible agents (MCP.md). The MCP server is a
presentation layer with **zero business logic** (MCP.md §3): it translates MCP
tool invocations into single Memory Kernel operations, owns exactly one kernel
instance, and contains no engine imports. Determinism is preserved (MCP.md §11):
every tool returns a JSON envelope a client can branch on without parsing
arbitrary prose.

## 2. Tool surface

Exactly the twelve documented tools (MCP.md §4), registered with stable names
and JSON schemas. Each tool maps 1:1 to a kernel operation and runs as the
`system` principal (`SYSTEM_PRINCIPAL` — trusted local environment, MCP.md §9):

| Tool | Kernel operation |
| --- | --- |
| create_memory | `create` |
| get_memory | `get` |
| search_memory | `search` |
| update_memory | `update` |
| delete_memory | `delete` |
| archive_memory | `archive` |
| list_memories | `list_memories` |
| list_versions | `list_versions` |
| create_relationship | `create_relationship` |
| delete_relationship | `delete_relationship` |
| related_memories | `get_relationships` |
| system_health | `health` |

## 3. Module layout

```
backend/src/memos/mcp/
    __init__.py        # exports create_mcp_server
    server.py          # create_mcp_server(): FastMCP factory, instructions, wiring
    tools.py           # McpTools: twelve tool callables bound to an injected kernel
    resources.py       # read-only resources (memos://memory/{id}, /versions, /relationships, statistics, config, health)
    errors.py          # envelope builders + call_kernel(): kernel/domain error -> MCP code
    __main__.py        # python -m memos.mcp: stdio entry point
backend/tests/
    test_mcp.py
```

`create_mcp_server(kernel=None, settings=None)` mirrors `create_app` in the API
layer: an injected kernel for tests, else a kernel built via `build_kernel`.
Resource handlers reuse the same envelope builders and read-only kernel
operations.

## 4. Response envelope

Success: `{"success": true, "data": ...}`
Error:   `{"success": false, "error": {"code", "message", "details"}}`

Tools return the envelope as JSON text content. Exceptions are not raised to
the MCP transport except for unhandled, unexpected failures — which `call_kernel`
collapses to `INTERNAL_ERROR` / "internal error" with **no internal details
leaked** (MCP.md §8: sensitive details never exposed).

## 5. Error mapping

Kernel emits five codes (Security.md §10). The MCP vocabulary maps 1:1 (MCP.md §8):

| KernelError code | MCP code |
| --- | --- |
| INVALID_REQUEST | INVALID_INPUT |
| NOT_FOUND | MEMORY_NOT_FOUND |
| STORAGE_FAILURE | STORAGE_FAILURE |
| PERMISSION_DENIED | PERMISSION_DENIED |
| INTERNAL_ERROR | INTERNAL_ERROR |

Argument coercion failures (`ValueError`/`TypeError` in the tool layer) map to
`INVALID_INPUT`. Anything else collapses to `INTERNAL_ERROR`.

## 6. Implementation checklist

1. Add `backend/src/memos/mcp/` package (no new runtime deps: `mcp` and
   `mcp[cli]` were already added for the MCP server).
2. Envelope + `call_kernel` helper in `errors.py`; `ValueError`/`TypeError`
   maps to INVALID_INPUT; unexpected exceptions to INTERNAL_ERROR with no leak.
3. `McpTools` with the twelve tools, injected kernel, `SYSTEM_PRINCIPAL` runs.
4. Resources per MCP.md §7 (read-only, JSON text content).
5. `create_mcp_server` factory + `__main__.py` stdio entry.
6. Tests in `backend/tests/test_mcp.py` using
   `mcp.shared.memory.create_connected_server_and_client_session`:
   - registration of exactly the twelve tools + usable schemas,
   - envelope shape for success and error,
   - error mapping: MEMORY_NOT_FOUND, INVALID_INPUT, STORAGE_FAILURE,
     INTERNAL_ERROR without leak,
   - CRUD + archive/delete lifecycle, list filters, ranked search,
     relationship lifecycle, versions, system health,
   - the six read-only resources (memory, versions, relationships,
     statistics, config, health).
7. Full suite green; README Current Status updated; commit.
