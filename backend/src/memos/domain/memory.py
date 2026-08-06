"""Domain model for MemOS.

This module defines the core entities that make up the MemOS domain: the
immutable :class:`MemoryObject`, the lifecycle state machine, and the
:class:`Relationship` graph edges. Domain entities carry no storage or
network concerns; they are pure data with validation rules enforced by the
Memory Kernel.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def now_utc() -> datetime:
    """Return the current UTC timestamp with timezone information."""
    return datetime.now(timezone.utc)


class PermissionLevel(str, Enum):
    """Access-control classification for a memory."""

    PRIVATE = "private"
    SYSTEM = "system"


class MemoryType(str, Enum):
    """Semantic classification of memory content."""

    FACT = "fact"
    EPISODIC = "episodic"
    PROCEDURAL = "procedural"
    SEMANTIC = "semantic"
    RELATIONSHIP = "relationship"
    PREFERENCE = "preference"
    GENERAL = "general"


class LifecycleState(str, Enum):
    """States of the memory lifecycle state machine."""

    CREATED = "created"
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"

    @classmethod
    def valid_transitions(cls, from_state: "LifecycleState") -> set["LifecycleState"]:
        """Return the set of states reachable from ``from_state``."""
        transitions: Dict[LifecycleState, set[LifecycleState]] = {
            cls.CREATED: {cls.ACTIVE, cls.DELETED},
            cls.ACTIVE: {cls.ARCHIVED, cls.DELETED},
            cls.ARCHIVED: {cls.ACTIVE, cls.DELETED},
            cls.DELETED: set(),
        }
        return transitions.get(from_state, set())


class RelationshipType(str, Enum):
    """Kinds of typed edges in the memory graph."""

    RELATED_TO = "related_to"
    CAUSES = "causes"
    DEPENDS_ON = "depends_on"
    PART_OF = "part_of"
    CONTRADICTS = "contradicts"
    REPLACES = "replaces"
    REFERENCES = "references"
    MENTIONS = "mentions"


@dataclass(frozen=True)
class Confidence:
    """Confidence metadata attached to a memory.

    ``score`` is a float in ``[0, 1]``. ``sources`` records where the
    confidence estimate came from (e.g. ``"user"``, ``"model:gpt-4"``,
    ``"retrieval_consensus"``).
    """

    score: float
    sources: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"Confidence score must be in [0, 1], got {self.score}")


@dataclass(frozen=True)
class SemanticScore:
    """A scored component used by the Importance Engine."""

    attention: float
    repetition: float
    relevance: float
    emotional_intensity: float

    @property
    def combined(self) -> float:
        """Weighted combination of the semantic dimensions (0..1)."""
        # Base weights favour attention and relevance; repetition and
        # emotional intensity act as modifiers.
        return (
            0.40 * self.attention
            + 0.25 * self.relevance
            + 0.20 * self.repetition
            + 0.15 * self.emotional_intensity
        )


@dataclass(frozen=True)
class ImportanceScore:
    """Importance estimate produced by the Importance Engine."""

    raw_score: float
    importance: float  # rescaled continuous score
    category: str
    confidence: float
    components: Dict[str, float] = field(default_factory=dict)


@dataclass
class MemoryObject:
    """The core immutable memory entity.

    Immutability semantics: once created, the identity, ownership, and
    content core cannot be mutated in place. "Updates" produce a new
    ``version``; :attr:`version` increments monotonically for an entity
    (stable :attr:`memory_id`).
    """

    # ---- content (metadata core) ---------------------------------------
    content: str

    # ---- identity (immutable) -------------------------------------------
    memory_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    owner_id: str = "default"

    # ---- type metadata ----------------------------------------------------
    type: MemoryType = MemoryType.GENERAL
    permission: PermissionLevel = PermissionLevel.PRIVATE
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ---- lifecycle --------------------------------------------------------
    state: LifecycleState = LifecycleState.ACTIVE
    version: int = 1
    created_at: datetime = field(default_factory=now_utc)
    updated_at: datetime = field(default_factory=now_utc)
    last_accessed_at: Optional[datetime] = None
    access_count: int = 0

    # ---- importance & confidence ---------------------------------------
    importance: float = 0.5
    importance_category: str = "medium"
    confidence: float = 0.5

    # ---- embeddings & graph (populated by storage/engines; not part of identity)
    embedding: Optional[List[float]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Serialize enums and datetimes to JSON-safe primitives
        for key, value in list(d.items()):
            if isinstance(value, Enum):
                d[key] = value.value
            elif isinstance(value, datetime):
                d[key] = value.isoformat()
        d["embedding"] = self.embedding
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryObject":
        cleaned = dict(data)
        cleaned["type"] = MemoryType(cleaned["type"])
        cleaned["state"] = LifecycleState(cleaned["state"])
        cleaned["permission"] = PermissionLevel(cleaned["permission"])
        return cls(**cleaned)