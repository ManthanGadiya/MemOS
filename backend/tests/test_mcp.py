"""Tests for the MemOS MCP server layer.

Covers the MCP contract from docs/MCP.md:

- the server registers exactly the twelve documented tools,
- every tool returns the deterministic success/error envelope
  (MCP.md sections 5 and 11),
- kernel errors map to the documented MCP error vocabulary
  (MCP.md section 8): INVALID_INPUT, MEMORY_NOT_FOUND, PERMISSION_DENIED,
  STORAGE_FAILURE, INTERNAL_ERROR — without leaking internals,
- CRUD, lifecycle, search, relationships, versions, and health work end to
  end against a real kernel on a temp SQLite database,
- the read-only resources (MCP.md section 7) return JSON for memory,
  versions, relationships, statistics, configuration, and health.

Each test opens its own client session: the anyio task group backing a session
must be entered and exited in the same asyncio task, so sessions cannot be
managed by a pytest fixture.
"""

import json
from contextlib import asynccontextmanager

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from memos.config.settings import Settings
from memos.domain.exceptions import StorageError
from memos.domain.memory import LifecycleState, MemoryObject
from memos.embedding.hash_embedder import HashEmbedder
from memos.engines import MemoryEngine
from memos.engines.graph import GraphEngine
from memos.engines.importance import ImportanceEngine
from memos.engines.permission import PermissionEngine
from memos.engines.retrieval import RetrievalEngine
from memos.engines.version import VersionEngine
from memos.kernel.audit import InMemoryAuditStore
from memos.kernel.events import InMemoryEventBus
from memos.kernel.kernel import MemoryKernel
from memos.kernel.validation import RequestValidator
from memos.mcp.server import create_mcp_server
from memos.storage.in_memory_graph import InMemoryGraphStore
from memos.storage.in_memory_vector import InMemoryVectorStore
from memos.storage.sqlite_metadata import SQLiteMetadataStore

DOCUMENTED_TOOLS = {
    "create_memory",
    "get_memory",
    "search_memory",
    "update_memory",
    "delete_memory",
    "archive_memory",
    "list_memories",
    "list_versions",
    "create_relationship",
    "delete_relationship",
    "related_memories",
    "system_health",
}


class CrashingMetadataStore(SQLiteMetadataStore):
    """Raise an *untyped* exception on the next ``create`` so the server must
    collapse it to INTERNAL_ERROR without leaking the message."""

    def __init__(self, database_path) -> None:
        super().__init__(database_path)
        self._fail_once = True

    def create(self, obj: MemoryObject) -> MemoryObject:
        if self._fail_once:
            self._fail_once = False
            raise RuntimeError("boom: sqlite driver leaked a traceback")
        return super().create(obj)


class StorageFailureMetadataStore(SQLiteMetadataStore):
    """Raise a structured ``StorageError`` on the next ``create``."""

    def __init__(self, database_path) -> None:
        super().__init__(database_path)
        self._fail_once = True

    def create(self, obj: MemoryObject) -> MemoryObject:
        if self._fail_once:
            self._fail_once = False
            raise StorageError("metadata store unavailable")
        return super().create(obj)


def build_test_kernel(tmp_path, *, metadata_store=None) -> MemoryKernel:
    """Assemble a MemoryKernel with injected stores (mirrors factory wiring)."""
    settings = Settings()
    metadata_store = metadata_store or SQLiteMetadataStore(tmp_path / "mcp_test.db")
    vector_store = InMemoryVectorStore()
    graph_store = InMemoryGraphStore()

    permission_engine = PermissionEngine(settings)
    importance_engine = ImportanceEngine(settings)
    version_engine = VersionEngine()
    graph_engine = GraphEngine(
        graph_store,
        node_validator=lambda mid: (m := metadata_store.get(mid)) is not None
        and m.state is LifecycleState.ACTIVE,
    )
    memory_engine = MemoryEngine(
        metadata_store=metadata_store,
        vector_store=vector_store,
        graph_store=graph_store,
        embedder=HashEmbedder(),
        importance_engine=importance_engine,
        version_engine=version_engine,
        graph_engine=graph_engine,
        permission_engine=permission_engine,
        settings=settings,
    )
    retrieval_engine = RetrievalEngine(
        metadata_store=metadata_store,
        vector_store=vector_store,
        graph_engine=graph_engine,
        embedder=HashEmbedder(),
        permission_engine=permission_engine,
        settings=settings,
    )

    return MemoryKernel(
        settings=settings,
        memory_engine=memory_engine,
        version_engine=version_engine,
        importance_engine=importance_engine,
        graph_engine=graph_engine,
        permission_engine=permission_engine,
        retrieval_engine=retrieval_engine,
        metadata_store=metadata_store,
        vector_store=vector_store,
        graph_store=graph_store,
        audit_store=InMemoryAuditStore(),
        event_bus=InMemoryEventBus(),
        validator=RequestValidator(settings),
    )


@pytest.fixture
def mcp_server(tmp_path):
    """A MemOS MCP server backed by a real kernel on a fresh SQLite DB."""
    kernel = build_test_kernel(tmp_path)
    server = create_mcp_server(kernel=kernel)
    yield server
    kernel.close()


@asynccontextmanager
async def open_session(server):
    """Open an MCP client session for the given server."""
    async with create_connected_server_and_client_session(server) as session:
        yield session


async def call_tool(session, tool_name: str, arguments: dict | None = None) -> dict:
    """Call a tool and parse its JSON envelope from the text content."""
    result = await session.call_tool(tool_name, arguments or {})
    assert result.isError is False, f"{tool_name} failed on the wire: {result.content}"
    text = result.content[0].text
    return json.loads(text)


async def read_resource(session, uri: str) -> dict:
    """Read a resource and parse its JSON envelope from the text content."""
    result = await session.read_resource(uri)
    return json.loads(result.contents[0].text)


async def create_memory(session, content: str, **overrides) -> str:
    payload = await call_tool(session, "create_memory", {"content": content, **overrides})
    assert payload["success"] is True, payload
    return payload["data"]["memory"]["memory_id"]


# ----------------------------------------------------------------------
# Tool registration (MCP.md section 4)
# ----------------------------------------------------------------------


async def test_exposes_exactly_the_documented_tools(mcp_server):
    async with open_session(mcp_server) as session:
        result = await session.list_tools()
        names = {tool.name for tool in result.tools}
        assert names == DOCUMENTED_TOOLS


async def test_tools_generate_usable_schemas(mcp_server):
    async with open_session(mcp_server) as session:
        result = await session.list_tools()
        by_name = {tool.name: tool for tool in result.tools}
        schema = by_name["create_memory"].inputSchema
        assert "content" in schema.get("properties", {})
        assert schema.get("required") == ["content"]


# ----------------------------------------------------------------------
# Envelope (MCP.md section 5 and 11)
# ----------------------------------------------------------------------


async def test_create_returns_success_envelope(mcp_server):
    async with open_session(mcp_server) as session:
        payload = await call_tool(
            session,
            "create_memory",
            {"content": "hello world", "title": "Hi", "tags": ["greeting"]},
        )
        assert payload["success"] is True
        data = payload["data"]
        assert data["status"] == "created"
        assert data["memory"]["content"] == "hello world"
        assert data["memory"]["title"] == "Hi"
        assert data["memory"]["tags"] == ["greeting"]


async def test_error_envelope_shape(mcp_server):
    async with open_session(mcp_server) as session:
        payload = await call_tool(session, "get_memory", {"memory_id": "does-not-exist"})
        assert payload["success"] is False
        error = payload["error"]
        assert set(error) == {"code", "message", "details"}


# ----------------------------------------------------------------------
# Error mapping (MCP.md section 8)
# ----------------------------------------------------------------------


async def test_missing_memory_is_memory_not_found(mcp_server):
    async with open_session(mcp_server) as session:
        payload = await call_tool(session, "get_memory", {"memory_id": "does-not-exist"})
        assert payload["error"]["code"] == "MEMORY_NOT_FOUND"


async def test_invalid_input_enum(mcp_server):
    async with open_session(mcp_server) as session:
        payload = await call_tool(
            session,
            "create_memory",
            {"content": "x", "memory_type": "bogus"},
        )
        assert payload["error"]["code"] == "INVALID_INPUT"


async def test_storage_failure_is_storage_failure(tmp_path):
    kernel = build_test_kernel(
        tmp_path, metadata_store=StorageFailureMetadataStore(tmp_path / "sf.db")
    )
    server = create_mcp_server(kernel=kernel)
    async with open_session(server) as session:
        payload = await call_tool(session, "create_memory", {"content": "boom"})
    kernel.close()
    assert payload["error"]["code"] == "STORAGE_FAILURE"


async def test_internal_failure_is_internal_error_without_leak(tmp_path):
    kernel = build_test_kernel(
        tmp_path, metadata_store=CrashingMetadataStore(tmp_path / "crash.db")
    )
    server = create_mcp_server(kernel=kernel)
    async with open_session(server) as session:
        payload = await call_tool(session, "create_memory", {"content": "boom"})
    kernel.close()
    assert payload["error"]["code"] == "INTERNAL_ERROR"
    assert "boom" not in payload["error"]["message"]
    assert "traceback" not in json.dumps(payload)


# ----------------------------------------------------------------------
# CRUD and lifecycle
# ----------------------------------------------------------------------


async def test_create_get_update(mcp_server):
    async with open_session(mcp_server) as session:
        memory_id = await create_memory(
            session,
            "original content",
            title="My Memory",
            tags=["alpha", "beta"],
            metadata={"source": "test"},
        )
        assert memory_id

        fetched = (await call_tool(session, "get_memory", {"memory_id": memory_id}))["data"]
        assert fetched["content"] == "original content"
        assert fetched["title"] == "My Memory"
        assert fetched["tags"] == ["alpha", "beta"]
        assert fetched["version"] == 1

        updated = (
            await call_tool(session, "update_memory", {"memory_id": memory_id, "content": "changed"})
        )["data"]
        assert updated["content"] == "changed"
        assert updated["version"] == 2


async def test_archive_memory(mcp_server):
    async with open_session(mcp_server) as session:
        memory_id = await create_memory(session, "to archive")
        payload = await call_tool(session, "archive_memory", {"memory_id": memory_id})
        assert payload["data"]["status"] == "archived"
        assert payload["data"]["memory"]["state"] == "archived"


async def test_delete_memory(mcp_server):
    async with open_session(mcp_server) as session:
        memory_id = await create_memory(session, "to delete")
        payload = await call_tool(session, "delete_memory", {"memory_id": memory_id})
        assert payload["data"] == {"memory_id": memory_id, "deleted": True}

        # DELETED is terminal: subsequent reads report MEMORY_NOT_FOUND.
        read = await call_tool(session, "get_memory", {"memory_id": memory_id})
        assert read["error"]["code"] == "MEMORY_NOT_FOUND"


async def test_list_memories_filters(mcp_server):
    async with open_session(mcp_server) as session:
        await create_memory(session, "alice memory", owner_id="alice")
        await create_memory(session, "bob memory", owner_id="bob")

        listed = await call_tool(session, "list_memories", {"owner_id": "alice"})
        owners = {m["owner_id"] for m in listed["data"]["memories"]}
        assert owners == {"alice"}


# ----------------------------------------------------------------------
# Search
# ----------------------------------------------------------------------


async def test_search_returns_ranked_results(mcp_server):
    async with open_session(mcp_server) as session:
        await create_memory(session, "the quick brown fox jumps over the lazy dog")
        await create_memory(session, "a completely unrelated note about weather patterns")

        payload = await call_tool(session, "search_memory", {"query": "quick brown fox", "top_k": 5})
        assert payload["success"] is True
        results = payload["data"]["results"]
        assert payload["data"]["count"] == len(results) >= 1
        first = results[0]
        assert set(first) == {
            "memory",
            "score",
            "similarity",
            "importance",
            "recency",
            "graph_connectivity",
        }
        assert "fox" in first["memory"]["content"]


# ----------------------------------------------------------------------
# Relationships
# ----------------------------------------------------------------------


async def test_relationship_lifecycle(mcp_server):
    async with open_session(mcp_server) as session:
        source_id = await create_memory(session, "source memory")
        target_id = await create_memory(session, "target memory")

        added = await call_tool(
            session,
            "create_relationship",
            {"source_memory": source_id, "target_memory": target_id, "relationship_type": "related_to", "weight": 0.8},
        )
        relationship = added["data"]
        assert relationship["source_id"] == source_id
        assert relationship["target_id"] == target_id
        assert relationship["type"] == "related_to"

        listed = await call_tool(session, "related_memories", {"memory_id": source_id})
        assert listed["data"]["count"] == 1
        relationship_id = listed["data"]["relationships"][0]["relationship_id"]

        deleted = await call_tool(session, "delete_relationship", {"relationship_id": relationship_id})
        assert deleted["data"]["deleted"] is True

        listed = await call_tool(session, "related_memories", {"memory_id": source_id})
        assert listed["data"]["relationships"] == []


# ----------------------------------------------------------------------
# Versions
# ----------------------------------------------------------------------


async def test_list_versions(mcp_server):
    async with open_session(mcp_server) as session:
        memory_id = await create_memory(session, "version one")
        await call_tool(session, "update_memory", {"memory_id": memory_id, "content": "version two"})

        payload = await call_tool(session, "list_versions", {"memory_id": memory_id})
        versions = payload["data"]["versions"]
        assert len(versions) == 2
        assert versions[0]["content"] == "version one"
        assert versions[1]["content"] == "version two"


# ----------------------------------------------------------------------
# Health
# ----------------------------------------------------------------------


async def test_system_health(mcp_server):
    async with open_session(mcp_server) as session:
        payload = await call_tool(session, "system_health")
        data = payload["data"]
        assert data["status"] == "ok"
        assert data["kernel"] == "ok"
        assert data["storage"] == "ok"
        assert data["mcp"] == "ok"


# ----------------------------------------------------------------------
# Resources (MCP.md section 7)
# ----------------------------------------------------------------------


async def test_memory_resource(mcp_server):
    async with open_session(mcp_server) as session:
        memory_id = await create_memory(session, "resource memory")
        payload = await read_resource(session, f"memos://memory/{memory_id}")
        assert payload["success"] is True
        assert payload["data"]["memory_id"] == memory_id
        assert payload["data"]["content"] == "resource memory"


async def test_versions_resource(mcp_server):
    async with open_session(mcp_server) as session:
        memory_id = await create_memory(session, "version one")
        await call_tool(session, "update_memory", {"memory_id": memory_id, "content": "version two"})
        payload = await read_resource(session, f"memos://memory/{memory_id}/versions")
        assert len(payload["data"]) == 2


async def test_relationships_resource(mcp_server):
    async with open_session(mcp_server) as session:
        source_id = await create_memory(session, "source")
        target_id = await create_memory(session, "target")
        await call_tool(
            session,
            "create_relationship",
            {"source_memory": source_id, "target_memory": target_id, "relationship_type": "references"},
        )
        payload = await read_resource(session, f"memos://memory/{source_id}/relationships")
        assert len(payload["data"]) == 1
        assert payload["data"][0]["type"] == "references"


async def test_statistics_config_health_resources(mcp_server):
    async with open_session(mcp_server) as session:
        await create_memory(session, "one for stats")

        statistics = await read_resource(session, "memos://statistics")
        assert set(statistics["data"]) == {"memory_count", "relationship_count", "audit_count"}
        assert statistics["data"]["memory_count"] >= 1

        config = await read_resource(session, "memos://config")
        assert "app_name" in config["data"]
        assert "database_path" not in config["data"]

        health = await read_resource(session, "memos://health")
        assert health["data"]["kernel"] == "ok"
        assert health["data"]["metadata_store"] == "ok"