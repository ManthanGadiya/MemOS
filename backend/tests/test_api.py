"""Tests for the MemOS REST API layer.

Covers the REST API contract from docs/API.md and docs/SystemArchitecture.md
(REST API chapter), SRS section 13.3 (response envelope) and section 13.7
(error mapping), and Security.md section 10 (three client-visible codes):

- every response uses the documented success/error envelope,
- request ids are honored from ``X-Request-ID`` and echoed in the response,
- kernel errors map 1:1 (403/400/500) without leaking internals,
- validation failures normalize to ``INVALID_REQUEST`` (400),
- CRUD, lifecycle, search, relationships, versions, and system endpoints
  work end to end against a real kernel on a temp SQLite database,
- a raw host failure collapses to ``INTERNAL_ERROR`` (500).
"""

import pytest
from fastapi.testclient import TestClient

from memos.api import create_app
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
from memos.storage.in_memory_graph import InMemoryGraphStore
from memos.storage.in_memory_vector import InMemoryVectorStore
from memos.storage.sqlite_metadata import SQLiteMetadataStore

API_V1 = "/api/v1"


class CrashingMetadataStore(SQLiteMetadataStore):
    """Raise an *untyped* exception on the next ``create`` so the API must
    collapse it to a 500 without leaking the message."""

    def __init__(self, database_path) -> None:
        super().__init__(database_path)
        self._fail_once = True

    def create(self, obj: MemoryObject) -> MemoryObject:
        if self._fail_once:
            self._fail_once = False
            raise RuntimeError("boom: sqlite driver leaked a traceback")
        return super().create(obj)


def build_test_kernel(tmp_path, *, metadata_store=None) -> MemoryKernel:
    """Assemble a MemoryKernel with injected stores (mirrors factory wiring)."""
    settings = Settings()
    metadata_store = metadata_store or SQLiteMetadataStore(tmp_path / "api_test.db")
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
def client(tmp_path):
    """A TestClient backed by a real kernel on a fresh SQLite database."""
    kernel = build_test_kernel(tmp_path)
    with TestClient(create_app(kernel=kernel)) as test_client:
        yield test_client
    kernel.close()


def create_memory(client, content: str, **overrides) -> str:
    body = {"content": content, **overrides}
    response = client.post(f"{API_V1}/memories", json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"]["memory_id"]


# ----------------------------------------------------------------------
# Envelope and request identity
# ----------------------------------------------------------------------


def test_success_envelope_shape(client):
    response = client.post(
        f"{API_V1}/memories", json={"content": "hello world"},
        headers={"X-Request-ID": "req-abc-123"},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"success", "request_id", "timestamp", "duration_ms", "data", "metadata"}
    assert body["success"] is True
    assert body["request_id"] == "req-abc-123"
    assert body["timestamp"]
    assert body["duration_ms"] >= 0
    assert body["data"]["content"] == "hello world"
    assert response.headers["X-Request-ID"] == "req-abc-123"


def test_request_id_generated_when_absent(client):
    memory_id = create_memory(client, "no header")
    response = client.get(f"{API_V1}/memories/{memory_id}")
    body = response.json()
    assert body["request_id"]
    assert response.headers["X-Request-ID"] == body["request_id"]


def test_error_envelope_shape(client):
    response = client.post(f"{API_V1}/memories", json={"content": ""})
    assert response.status_code == 400
    body = response.json()
    assert set(body) == {"success", "request_id", "timestamp", "duration_ms", "error"}
    assert body["success"] is False
    assert body["error"]["code"] == "INVALID_REQUEST"
    assert body["error"]["message"]
    assert "details" in body["error"]


# ----------------------------------------------------------------------
# Error mapping (Security.md section 10)
# ----------------------------------------------------------------------


def test_missing_memory_is_404_not_found(client):
    response = client.get(f"{API_V1}/memories/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["message"]
    assert "details" in body["error"]


def test_validation_failure_is_400_invalid_request(client):
    response = client.post(f"{API_V1}/memories", json={"content": ""})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert "errors" in response.json()["error"]["details"]


def test_permission_denied_is_403(client):
    memory_id = create_memory(client, "alice private", owner_id="alice")
    response = client.get(
        f"{API_V1}/memories/{memory_id}",
        headers={"X-Principal-ID": "bob"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


def test_internal_failure_is_500_without_leak(tmp_path):
    kernel = build_test_kernel(
        tmp_path, metadata_store=CrashingMetadataStore(tmp_path / "crash.db")
    )
    with TestClient(create_app(kernel=kernel)) as client:
        response = client.post(f"{API_V1}/memories", json={"content": "boom"})
    kernel.close()
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "boom" not in body["error"]["message"]
    assert "traceback" not in response.text


# ----------------------------------------------------------------------
# CRUD and lifecycle
# ----------------------------------------------------------------------


def test_create_get_update(client):
    memory_id = create_memory(
        client,
        "original content",
        title="My Memory",
        tags=["alpha", "beta"],
        metadata={"source": "test"},
    )
    assert memory_id

    fetched = client.get(f"{API_V1}/memories/{memory_id}").json()["data"]
    assert fetched["content"] == "original content"
    assert fetched["title"] == "My Memory"
    assert fetched["tags"] == ["alpha", "beta"]
    assert fetched["version"] == 1

    updated = client.put(
        f"{API_V1}/memories/{memory_id}",
        json={"content": "changed content"},
    ).json()["data"]
    assert updated["content"] == "changed content"
    assert updated["version"] == 2


def test_archive_restore(client):
    memory_id = create_memory(client, "to archive")
    archived = client.put(f"{API_V1}/memories/{memory_id}/archive").json()["data"]
    assert archived["state"] == "archived"

    restored = client.put(f"{API_V1}/memories/{memory_id}/restore").json()["data"]
    assert restored["state"] == "active"


def test_delete(client):
    memory_id = create_memory(client, "to delete")
    response = client.delete(f"{API_V1}/memories/{memory_id}")
    assert response.status_code == 200
    assert response.json()["data"] == {"memory_id": memory_id, "deleted": True}

    # DELETED is terminal: subsequent reads fail with NOT_FOUND (404).
    read = client.get(f"{API_V1}/memories/{memory_id}")
    assert read.status_code == 404


def test_list_memories_pagination(client):
    for i in range(5):
        create_memory(client, f"memory number {i}")
    response = client.get(f"{API_V1}/memories", params={"limit": 2, "offset": 1})
    body = response.json()
    assert len(body["data"]) == 2
    assert body["metadata"]["limit"] == 2
    assert body["metadata"]["offset"] == 1


def test_list_memories_filter_by_owner(client):
    create_memory(client, "alice memory", owner_id="alice")
    create_memory(client, "bob memory", owner_id="bob")
    response = client.get(f"{API_V1}/memories", params={"owner_id": "alice"})
    owners = {m["owner_id"] for m in response.json()["data"]}
    assert owners == {"alice"}


# ----------------------------------------------------------------------
# Search
# ----------------------------------------------------------------------


def test_search_returns_ranked_results(client):
    create_memory(client, "the quick brown fox jumps over the lazy dog")
    create_memory(client, "a completely unrelated note about weather patterns")

    body = {"query": "quick brown fox", "top_k": 5}
    response = client.post(f"{API_V1}/search", json=body)
    assert response.status_code == 200
    payload = response.json()
    assert payload["metadata"]["count"] >= 1
    first = payload["data"][0]
    assert set(first) == {
        "memory",
        "score",
        "similarity",
        "importance",
        "recency",
        "graph_connectivity",
    }
    assert first["memory"]["content"] == "the quick brown fox jumps over the lazy dog"


# ----------------------------------------------------------------------
# Relationships
# ----------------------------------------------------------------------


def test_relationship_lifecycle(client):
    source_id = create_memory(client, "source memory")
    target_id = create_memory(client, "target memory")

    added = client.post(
        f"{API_V1}/memories/{source_id}/relationships",
        json={"target_id": target_id, "relationship_type": "related_to", "weight": 0.8},
    )
    assert added.status_code == 200, added.text
    relationship = added.json()["data"]
    assert relationship["source_id"] == source_id
    assert relationship["target_id"] == target_id
    assert relationship["type"] == "related_to"

    listed = client.get(f"{API_V1}/memories/{source_id}/relationships").json()["data"]
    assert len(listed) == 1
    relationship_id = listed[0]["relationship_id"]

    deleted = client.delete(
        f"{API_V1}/memories/{source_id}/relationships/{relationship_id}"
    )
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] is True

    listed = client.get(f"{API_V1}/memories/{source_id}/relationships").json()["data"]
    assert listed == []


# ----------------------------------------------------------------------
# Versions
# ----------------------------------------------------------------------


def test_versions_endpoints(client):
    memory_id = create_memory(client, "version one")
    client.put(f"{API_V1}/memories/{memory_id}", json={"content": "version two"})

    history = client.get(f"{API_V1}/memories/{memory_id}/versions")
    assert history.status_code == 200
    versions = history.json()["data"]
    assert len(versions) == 2
    assert versions[0]["content"] == "version one"
    assert versions[1]["content"] == "version two"

    snapshot = client.get(f"{API_V1}/memories/{memory_id}/versions/1")
    assert snapshot.status_code == 200
    assert snapshot.json()["data"]["content"] == "version one"


# ----------------------------------------------------------------------
# System endpoints
# ----------------------------------------------------------------------


def test_health(client):
    response = client.get(f"{API_V1}/health")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["kernel"] == "ok"
    assert data["metadata_store"] == "ok"


def test_system_status_and_statistics(client):
    create_memory(client, "one for stats")
    status = client.get(f"{API_V1}/system/status").json()["data"]
    assert status["app"] == "MemOS"
    assert status["storage_backend"] == "sqlite"
    assert status["statistics"]["memory_count"] >= 1

    stats = client.get(f"{API_V1}/dashboard/statistics").json()["data"]
    assert set(stats) == {"memory_count", "relationship_count", "audit_count"}


def test_config_exposes_only_safe_keys(client):
    data = client.get(f"{API_V1}/config").json()["data"]
    assert "app_name" in data
    assert "storage_backend" in data
    assert "database_path" not in data


def test_dashboard_health(client):
    response = client.get(f"{API_V1}/dashboard/health")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["app"] == "MemOS"
    assert data["version"] != ""
    assert data["kernel"] == "ok"
    assert data["metadata_store"] == "ok"


def test_dashboard_logs_returns_audit_records(client):
    create_memory(client, "log me")
    data = client.get(f"{API_V1}/dashboard/logs").json()["data"]
    assert data["total"] >= 1
    records = data["records"]
    assert any(
        record["operation"] == "create" and record["result"] == "SUCCESS"
        for record in records
    )
    # Every audit record is JSON-safe with the documented fields.
    first = records[0]
    assert set(first) >= {
        "timestamp",
        "request_id",
        "memory_id",
        "operation",
        "principal_id",
        "result",
        "operation_type",
    }


def test_dashboard_logs_filters(client):
    memory_id = create_memory(client, "filter me")
    # A foreign principal is denied (private memory), producing a DENIED record.
    denied_archive = client.put(
        f"{API_V1}/memories/{memory_id}/archive", headers={"X-Principal-ID": "dash-user"}
    )
    assert denied_archive.json()["success"] is False

    # The owner (system) can archive, producing a SUCCESS record.
    client.put(f"{API_V1}/memories/{memory_id}/archive")

    creates = client.get(
        f"{API_V1}/dashboard/logs", params={"operation": "create"}
    ).json()["data"]["records"]
    assert creates and all(record["operation"] == "create" for record in creates)

    archived = client.get(
        f"{API_V1}/dashboard/logs", params={"operation": "archive"}
    ).json()["data"]["records"]
    assert archived and all(record["operation"] == "archive" for record in archived)
    assert any(
        record["result"] == "SUCCESS" and record["memory_id"] == memory_id
        for record in archived
    )

    denied = client.get(
        f"{API_V1}/dashboard/logs", params={"result": "DENIED"}
    ).json()["data"]["records"]
    assert denied and all(record["result"] == "DENIED" for record in denied)


def test_dashboard_logs_pagination(client):
    for index in range(5):
        create_memory(client, f"page {index}")
    first_page = client.get(
        f"{API_V1}/dashboard/logs", params={"limit": 2, "offset": 0}
    ).json()["data"]
    second_page = client.get(
        f"{API_V1}/dashboard/logs", params={"limit": 2, "offset": 2}
    ).json()["data"]
    assert len(first_page["records"]) == 2
    assert len(second_page["records"]) == 2
    assert first_page["records"][0]["timestamp"] != second_page["records"][0]["timestamp"]


def test_dashboard_logs_invalid_filters(client):
    bad_operation = client.get(
        f"{API_V1}/dashboard/logs", params={"operation": "not-an-op"}
    ).json()
    assert bad_operation["success"] is False
    assert bad_operation["error"]["code"] == "INVALID_REQUEST"

    bad_result = client.get(
        f"{API_V1}/dashboard/logs", params={"result": "MAYBE"}
    ).json()
    assert bad_result["success"] is False
    assert bad_result["error"]["code"] == "INVALID_REQUEST"

    too_many = client.get(
        f"{API_V1}/dashboard/logs", params={"limit": 5000}
    ).json()
    assert too_many["success"] is False
    assert too_many["error"]["code"] == "INVALID_REQUEST"
