"""Retrieval Engine for MemOS.

The Retrieval Engine is the read-only subsystem that locates Memory Objects
relevant to an incoming query. It implements the deterministic hybrid
retrieval pipeline documented in ``docs/Algorithms.md`` (section 5) and the
ranking formula of section 6. Retrieval never modifies memory.

Fusion formula (``docs/Algorithms.md`` section 6.1)::

    S = α * sim + β * importance_n + γ * confidence + δ * recency_n + ε * graph_n

with α/β/γ/δ/ε taken from ``settings.rank_alpha .. rank_epsilon``
(defaults 0.40 / 0.30 / 0.15 / 0.10 / 0.05, which sum to 1.0). Every
component is normalized to [0, 1]:

- ``sim``: cosine similarity clamped to [0, 1]; 0.0 for memories without an
  embedding (they remain retrievable through the metadata keyword path).
- ``importance_n``: ``memory.importance / 100`` (docs pin importance to
  0..100).
- ``confidence``: ``memory.confidence`` (already in [0, 1]).
- ``recency_n``: ``1 / (1 + RECENCY_DECAY_CONSTANT * age_hours)`` using the
  documented decay constant ``0.002`` (section 6.2). Age is measured from
  ``last_accessed_at``, falling back to ``updated_at``.
- ``graph_n``: degree-based connectivity saturation
  ``min(degree / GRAPH_SATURATION, 1.0)`` (degree is the graph density
  signal exposed by the Graph Engine).

Result ordering is fully deterministic: candidates are sorted by final score
descending and ties are broken by ``memory_id`` ascending (section 11.2).

Lifecycle default: ``docs/Algorithms.md`` section 5.2 pins the default
lifecycle-state filter to ``ACTIVE``, so ARCHIVED and DELETED memories are
excluded from default searches. Pass ``state`` explicitly to override.

Note: section 6.4 ("query without embedding" weight renormalization) is not
implemented here: :meth:`RetrievalEngine.hybrid_search` always embeds the
query, and the pure keyword/tag modes keep their own ranking signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
from typing import Any, Dict, List, Tuple

from memos.config.settings import Settings
from memos.domain.exceptions import ValidationError
from memos.domain.memory import (
    LifecycleState,
    MemoryObject,
    MemoryType,
    now_utc,
)
from memos.embedding.protocol import EmbeddingProvider
from memos.engines.graph import GraphEngine
from memos.engines.permission import SYSTEM_PRINCIPAL, PermissionEngine
from memos.storage.protocols import MetadataStore, VectorStore

# docs/Algorithms.md section 6.2: recency_n = 1 / (1 + 0.002 * age_hours)
RECENCY_DECAY_CONSTANT: float = 0.002
# Relationship degree at which the connectivity signal saturates to 1.0.
GRAPH_SATURATION: float = 5.0
# Candidate pool per source is top_k * this multiplier, so post-filters and
# permission checks can still fill the requested top_k slots.
CANDIDATE_POOL_MULTIPLIER: int = 3
# Default traversal depth for graph_search (docs/Algorithms.md section 8.2).
DEFAULT_GRAPH_SEARCH_DEPTH: int = 2
# Default lifecycle state applied when no explicit state filter is given
# (docs/Algorithms.md section 5.2).
DEFAULT_SEARCH_STATE: LifecycleState = LifecycleState.ACTIVE


@dataclass
class ScoredMemory:
    """A ranked retrieval result with its explainable score components.

    ``score`` is the ranking signal used to order results for the retrieval
    mode that produced this result (the fused hybrid score for
    :meth:`RetrievalEngine.hybrid_search`, the pure similarity for
    :meth:`RetrievalEngine.semantic_search`, the keyword/tag overlap for the
    metadata/tag modes, and the depth-based graph score for
    :meth:`RetrievalEngine.graph_search`). ``similarity`` is always the
    cosine-similarity component (0.0 when no embedding is available).
    """

    memory: MemoryObject
    score: float
    similarity: float
    importance: float
    recency: float
    graph_connectivity: float


class RetrievalEngine:
    """Deterministic hybrid retrieval over the injected stores and engines.

    The engine is stateless between calls; all persistent state lives in the
    injected stores. Candidate selection and ranking are pure functions of
    the query and the stored memory metadata.
    """

    def __init__(
        self,
        metadata_store: MetadataStore,
        vector_store: VectorStore,
        graph_engine: GraphEngine,
        embedder: EmbeddingProvider,
        permission_engine: PermissionEngine,
        settings: Settings,
    ) -> None:
        self._metadata_store: MetadataStore = metadata_store
        self._vector_store: VectorStore = vector_store
        self._graph_engine: GraphEngine = graph_engine
        self._embedder: EmbeddingProvider = embedder
        self._permission_engine: PermissionEngine = permission_engine
        self._settings: Settings = settings

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def hybrid_search(
        self,
        query: str,
        top_k: int | None = None,
        owner_id: str | None = None,
        memory_type: MemoryType | None = None,
        state: LifecycleState | None = None,
        tags: list[str] | None = None,
        principal_id: str = SYSTEM_PRINCIPAL,
    ) -> List[ScoredMemory]:
        """Core retrieval: fuse vector similarity and metadata keywords.

        Candidates are gathered from (a) dense-vector semantic search over
        the embedded query and (b) metadata keyword search over content.
        Candidates are deduplicated by ``memory_id`` (keeping the higher
        individual similarity), post-filtered by the optional owner / type /
        state / tag filters, filtered through the permission engine for
        ``principal_id``, fused into the documented hybrid ranking formula,
        sorted descending (ties broken by ``memory_id`` ascending), and
        capped at ``top_k`` (default ``settings.default_top_k``).

        When ``state`` is ``None`` the documented default ``ACTIVE`` applies,
        so ARCHIVED and DELETED memories are excluded (see module docstring).

        Raises:
            ValidationError: if ``query`` is empty or whitespace only.
        """
        query = self._validate_query(query)
        effective_top_k = self._effective_top_k(top_k)
        pool_size = effective_top_k * CANDIDATE_POOL_MULTIPLIER

        candidates: Dict[str, Tuple[MemoryObject, float]] = {}

        query_vector = self._embedder.embed(query)
        for memory_id, raw_similarity in self._vector_store.search(
            query_vector, top_k=pool_size
        ):
            memory = self._metadata_store.get(memory_id)
            if memory is None:
                continue
            self._merge_candidate(
                candidates, memory, self._clamp_similarity(raw_similarity)
            )

        for memory in self._metadata_store.search_metadata(query, limit=pool_size):
            self._merge_candidate(candidates, memory, 0.0)

        effective_state = DEFAULT_SEARCH_STATE if state is None else state
        filtered = [
            (memory, similarity)
            for memory, similarity in candidates.values()
            if self._matches_filters(
                memory, owner_id, memory_type, effective_state, tags
            )
        ]

        accessible = self._permission_engine.filter_accessible(
            [memory for memory, _ in filtered], principal_id
        )
        accessible_ids = {memory.memory_id for memory in accessible}
        filtered = [
            (memory, similarity)
            for memory, similarity in filtered
            if memory.memory_id in accessible_ids
        ]

        scored = [
            self._score_candidate(memory, similarity)
            for memory, similarity in filtered
        ]
        scored.sort(key=lambda item: (-item.score, item.memory.memory_id))
        return scored[:effective_top_k]

    def semantic_search(
        self,
        query: str,
        top_k: int | None = None,
        filter_payload: Dict[str, Any] | None = None,
    ) -> List[ScoredMemory]:
        """Pure vector similarity via ``vector_store.search``.

        Results are ranked by the clamped cosine similarity (the vector store
        ordering is re-stabilized with the ``memory_id`` tie-break). This is a
        primitive retrieval mode: no metadata filters or permission checks are
        applied here — use :meth:`hybrid_search` for permission-aware
        retrieval.

        Raises:
            ValidationError: if ``query`` is empty or whitespace only.
        """
        query = self._validate_query(query)
        effective_top_k = self._effective_top_k(top_k)
        query_vector = self._embedder.embed(query)

        scored: List[ScoredMemory] = []
        for memory_id, raw_similarity in self._vector_store.search(
            query_vector, top_k=effective_top_k, filter_payload=filter_payload
        ):
            memory = self._metadata_store.get(memory_id)
            if memory is None:
                continue
            similarity = self._clamp_similarity(raw_similarity)
            importance, recency, graph_connectivity = self._components(memory)
            scored.append(
                ScoredMemory(
                    memory=memory,
                    score=similarity,
                    similarity=similarity,
                    importance=importance,
                    recency=recency,
                    graph_connectivity=graph_connectivity,
                )
            )
        scored.sort(key=lambda item: (-item.score, item.memory.memory_id))
        return scored

    def metadata_search(
        self, query: str, top_k: int | None = None
    ) -> List[ScoredMemory]:
        """Keyword substring search via ``metadata_store.search_metadata``.

        Results are ranked by the query-term overlap with the memory content
        (a match signal in [0, 1]); ties are broken by ``memory_id``.

        Raises:
            ValidationError: if ``query`` is empty or whitespace only.
        """
        query = self._validate_query(query)
        effective_top_k = self._effective_top_k(top_k)
        pool_size = effective_top_k * CANDIDATE_POOL_MULTIPLIER

        scored: List[ScoredMemory] = []
        for memory in self._metadata_store.search_metadata(query, limit=pool_size):
            importance, recency, graph_connectivity = self._components(memory)
            scored.append(
                ScoredMemory(
                    memory=memory,
                    score=self._keyword_overlap_score(memory, query),
                    similarity=0.0,
                    importance=importance,
                    recency=recency,
                    graph_connectivity=graph_connectivity,
                )
            )
        scored.sort(key=lambda item: (-item.score, item.memory.memory_id))
        return scored[:effective_top_k]

    def tag_search(
        self, tags: List[str], top_k: int | None = None
    ) -> List[ScoredMemory]:
        """Tag search via ``metadata_store.search_tags``.

        Results are ranked by the fraction of requested tags present on the
        memory (a score in [0, 1]); ties are broken by ``memory_id``.

        Raises:
            ValidationError: if ``tags`` is empty.
        """
        if not tags:
            raise ValidationError("tags must be a non-empty list")
        effective_top_k = self._effective_top_k(top_k)
        pool_size = effective_top_k * CANDIDATE_POOL_MULTIPLIER

        scored: List[ScoredMemory] = []
        for memory in self._metadata_store.search_tags(tags, limit=pool_size):
            importance, recency, graph_connectivity = self._components(memory)
            scored.append(
                ScoredMemory(
                    memory=memory,
                    score=self._tag_overlap_score(memory, tags),
                    similarity=0.0,
                    importance=importance,
                    recency=recency,
                    graph_connectivity=graph_connectivity,
                )
            )
        scored.sort(key=lambda item: (-item.score, item.memory.memory_id))
        return scored[:effective_top_k]

    def graph_search(
        self,
        start_memory_id: str,
        max_depth: int = DEFAULT_GRAPH_SEARCH_DEPTH,
        top_k: int | None = None,
    ) -> List[ScoredMemory]:
        """Traverse from ``start_memory_id`` and return reachable neighbors.

        Uses ``graph_engine.traverse``; each reached target memory is scored
        by the documented depth formula ``1 / (1 + depth)`` (section 6.3), so
        shallower hops rank higher. When a node is reachable at several
        depths the shallowest depth wins. Results are capped at ``top_k``.
        """
        effective_top_k = self._effective_top_k(top_k)

        shallowest_depth: Dict[str, int] = {}
        for relationship, depth in self._graph_engine.traverse(
            start_memory_id, max_depth=max_depth
        ):
            target_id = relationship.target_id
            if target_id not in shallowest_depth or depth < shallowest_depth[target_id]:
                shallowest_depth[target_id] = depth

        scored: List[ScoredMemory] = []
        for target_id, depth in shallowest_depth.items():
            memory = self._metadata_store.get(target_id)
            if memory is None:
                continue
            importance, recency, graph_connectivity = self._components(memory)
            scored.append(
                ScoredMemory(
                    memory=memory,
                    score=1.0 / (1.0 + depth),
                    similarity=0.0,
                    importance=importance,
                    recency=recency,
                    graph_connectivity=graph_connectivity,
                )
            )
        scored.sort(key=lambda item: (-item.score, item.memory.memory_id))
        return scored[:effective_top_k]

    # ------------------------------------------------------------------
    # Scoring helpers
    # ------------------------------------------------------------------

    def _score_candidate(self, memory: MemoryObject, similarity: float) -> ScoredMemory:
        """Fuse the documented hybrid ranking formula for one candidate."""
        importance, recency, graph_connectivity = self._components(memory)
        final_score = (
            self._settings.rank_alpha * similarity
            + self._settings.rank_beta * importance
            + self._settings.rank_gamma * memory.confidence
            + self._settings.rank_delta * recency
            + self._settings.rank_epsilon * graph_connectivity
        )
        return ScoredMemory(
            memory=memory,
            score=final_score,
            similarity=similarity,
            importance=importance,
            recency=recency,
            graph_connectivity=graph_connectivity,
        )

    def _components(self, memory: MemoryObject) -> Tuple[float, float, float]:
        """Return ``(importance_n, recency_n, graph_connectivity)`` in [0, 1]."""
        return (
            self._importance_norm(memory),
            self._recency_norm(memory),
            self._graph_connectivity(memory.memory_id),
        )

    @staticmethod
    def _importance_norm(memory: MemoryObject) -> float:
        """Normalize the 0..100 importance scale to [0, 1]."""
        return max(0.0, min(1.0, memory.importance / 100.0))

    def _recency_norm(self, memory: MemoryObject) -> float:
        """Time-decay recency: ``1 / (1 + DECAY * age_hours)`` in [0, 1]."""
        reference_time = memory.last_accessed_at or memory.updated_at
        if reference_time is None:
            return 1.0
        if reference_time.tzinfo is None:
            # SQLite may hand back naive datetimes; treat them as UTC.
            reference_time = reference_time.replace(tzinfo=timezone.utc)
        age_seconds = max(0.0, (now_utc() - reference_time).total_seconds())
        age_hours = age_seconds / 3600.0
        return 1.0 / (1.0 + RECENCY_DECAY_CONSTANT * age_hours)

    def _graph_connectivity(self, memory_id: str) -> float:
        """Degree-based connectivity saturation in [0, 1]."""
        return min(self._graph_engine.degree(memory_id) / GRAPH_SATURATION, 1.0)

    @staticmethod
    def _clamp_similarity(value: float) -> float:
        """Clamp a raw cosine similarity into [0, 1]."""
        return max(0.0, min(1.0, value))

    # ------------------------------------------------------------------
    # Candidate gathering and filtering helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_candidate(
        candidates: Dict[str, Tuple[MemoryObject, float]],
        memory: MemoryObject,
        similarity: float,
    ) -> None:
        """Deduplicate by ``memory_id``, keeping the higher similarity."""
        current = candidates.get(memory.memory_id)
        if current is None or similarity > current[1]:
            candidates[memory.memory_id] = (memory, similarity)

    @staticmethod
    def _matches_filters(
        memory: MemoryObject,
        owner_id: str | None,
        memory_type: MemoryType | None,
        state: LifecycleState,
        tags: list[str] | None,
    ) -> bool:
        """Post-filter a candidate against the optional retrieval filters."""
        if owner_id is not None and memory.owner_id != owner_id:
            return False
        if memory_type is not None and memory.type is not memory_type:
            return False
        if state is not None and memory.state is not state:
            return False
        if tags and not any(tag in memory.tags for tag in tags):
            return False
        return True

    @staticmethod
    def _keyword_overlap_score(memory: MemoryObject, query: str) -> float:
        """Fraction of query terms present in the content (a [0, 1] match)."""
        terms = [term for term in query.split() if term]
        if not terms:
            return 1.0
        content_lower = memory.content.lower()
        matched = sum(1 for term in terms if term.lower() in content_lower)
        return matched / len(terms)

    @staticmethod
    def _tag_overlap_score(memory: MemoryObject, tags: List[str]) -> float:
        """Fraction of requested tags present on the memory (a [0, 1] match)."""
        if not tags:
            return 0.0
        matched = len(set(memory.tags) & set(tags))
        return matched / len(tags)

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    def _effective_top_k(self, top_k: int | None) -> int:
        """Resolve the requested ``top_k`` against the configured default."""
        return self._settings.default_top_k if top_k is None else top_k

    @staticmethod
    def _validate_query(query: str) -> str:
        """Ensure the query is a non-empty, stripped string."""
        if query is None or not query.strip():
            raise ValidationError("query must be a non-empty string")
        return query.strip()


__all__ = ["RetrievalEngine", "ScoredMemory"]
