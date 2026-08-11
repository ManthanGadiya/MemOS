"""Pydantic request and response models for the MemOS REST API.

The API consumes these models to validate input and builds ``data`` payloads
from them so responses stay typed and documented (SystemArchitecture.md REST
API chapter: pydantic response models are required).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from memos.domain.memory import LifecycleState, MemoryType, PermissionLevel
from memos.domain.relationship import RelationshipType
from memos.engines.retrieval import ScoredMemory
from memos.engines.version import MemoryVersion

# ----------------------------------------------------------------------
# Domain serializers (pydantic models for the ``data`` payloads)
# ----------------------------------------------------------------------


class MemoryOut(BaseModel):
    """Serialized Memory Object returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    content: str
    title: str = ""
    source: str = ""
    summary: str = ""

    memory_id: str
    namespace: str = "personal"
    owner_id: str = "default"

    type: MemoryType
    permission: PermissionLevel
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    state: LifecycleState
    version: int = 1
    created_at: datetime
    updated_at: datetime
    last_accessed_at: Optional[datetime] = None
    access_count: int = 0

    importance: float = 0.0
    importance_category: str = "negligible"
    confidence: float = 0.5

    embedding: Optional[List[float]] = None

    @classmethod
    def from_object(cls, memory: Any) -> "MemoryOut":
        return cls(**memory.to_dict())


class RelationshipOut(BaseModel):
    """Serialized Relationship returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    source_id: str
    target_id: str
    type: RelationshipType
    relationship_id: str
    weight: float = 1.0
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @classmethod
    def from_object(cls, relationship: Any) -> "RelationshipOut":
        return cls(**relationship.to_dict())


class MemoryVersionOut(BaseModel):
    """Serialized memory version snapshot returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    memory_id: str
    version: int
    content: str
    change_type: str
    created_at: datetime
    diff: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_object(cls, version: MemoryVersion) -> "MemoryVersionOut":
        return cls(**version.__dict__)


class SearchResultOut(BaseModel):
    """One ranked hybrid-search result with its score components."""

    memory: MemoryOut
    score: float
    similarity: float
    importance: float
    recency: float
    graph_connectivity: float

    @classmethod
    def from_object(cls, result: ScoredMemory) -> "SearchResultOut":
        return cls(
            memory=MemoryOut.from_object(result.memory),
            score=result.score,
            similarity=result.similarity,
            importance=result.importance,
            recency=result.recency,
            graph_connectivity=result.graph_connectivity,
        )


# ----------------------------------------------------------------------
# Request models
# ----------------------------------------------------------------------


class CreateMemoryRequest(BaseModel):
    """Body for ``POST /memories``."""

    content: str = Field(..., min_length=1)
    owner_id: str = "default"
    memory_type: Optional[MemoryType] = None
    namespace: str = "personal"
    title: str = ""
    source: str = ""
    summary: str = ""
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    permission: Optional[PermissionLevel] = None


class UpdateMemoryRequest(BaseModel):
    """Body for ``PUT /memories/{id}`` (partial update)."""

    content: Optional[str] = Field(default=None, min_length=1)
    memory_type: Optional[MemoryType] = None
    namespace: Optional[str] = None
    title: Optional[str] = None
    source: Optional[str] = None
    summary: Optional[str] = None
    tags: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


class SearchRequest(BaseModel):
    """Body for ``POST /search``."""

    query: str = Field(..., min_length=1)
    top_k: Optional[int] = Field(default=None, ge=1, le=100)
    owner_id: Optional[str] = None
    memory_type: Optional[MemoryType] = None
    state: Optional[LifecycleState] = None
    tags: Optional[List[str]] = None
    graph_expansion: bool = False


class AddRelationshipRequest(BaseModel):
    """Body for ``POST /memories/{id}/relationships``."""

    target_id: str
    relationship_type: RelationshipType = RelationshipType.RELATED_TO
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)