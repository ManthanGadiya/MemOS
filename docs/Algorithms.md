# Algorithms Specification

**Project:** MemOS (Memory Operating System)

**Document Version:** 1.0

**Status:** Draft

**Related Documents**

- PRD.md
- SRS.md
- MemoryTheory.md
- SystemArchitecture.md
- Database.md
- API.md
- Benchmark.md

---

# Table of Contents

1. Purpose
2. Design Principles
3. Importance Scoring
4. Confidence Scoring
5. Hybrid Retrieval Pipeline
6. Retrieval Ranking
7. Embedding Strategy
8. Graph Traversal
9. Version Management
10. Decay Model
11. Determinism Guarantees
12. Conclusion

---

# 1. Purpose

This document defines every algorithm used by MemOS Version 1.

The Software Requirements Specification (SRS) and System Architecture Specification reference this document for the exact scoring, ranking, traversal, and evolution algorithms.

Every algorithm in this document is:

- deterministic
- explainable
- storage independent
- model independent

No algorithm in Version 1 requires a language model.

---

# 2. Design Principles

The following principles govern every algorithm.

## AL-001

Every algorithm shall be deterministic.

The same inputs must always produce the same outputs.

## AL-002

Every score shall be explainable.

Each score exposes the factors that contributed to its value.

## AL-003

Scores shall be bounded.

- Importance: `0 ≤ score ≤ 100`
- Confidence: `0 ≤ confidence ≤ 1`
- Relationship weight: `0 ≤ weight ≤ 1`

## AL-004

No algorithm shall depend on a specific language model.

## AL-005

Algorithms shall operate on Memory Objects and relationship metadata, never on raw storage rows.

---

# 3. Importance Scoring

## 3.1 Definition

Importance measures the **long-term usefulness** of a Memory Object for future reasoning.

Importance is not correctness.

Importance is not recency.

Importance is not confidence.

Importance answers:

> "How valuable is this memory for future reasoning?"

## 3.2 Scale

Importance exists on a continuous scale.

```
0
↓
100
```

| Score Range | Category |
|-------------|----------|
| 0–20 | Negligible |
| 21–40 | Low |
| 41–60 | Moderate |
| 61–80 | High |
| 81–100 | Critical |

## 3.3 Contributing Factors

Version 1 computes importance using the following deterministic factors.

| Factor | Symbol | Description |
|--------|--------|-------------|
| Explicit user emphasis | `E` | The memory was explicitly marked important by the owner. `0` or `1`. |
| Memory type weight | `T` | Base weight for the memory type. See 3.4. |
| Relationship density | `R` | Normalized count of active relationships incident to the memory. |
| Retrieval frequency | `F` | Normalized number of successful retrievals. |
| Recency | `A` | Normalized age factor (newer memories receive a small base contribution). |

## 3.4 Memory Type Base Weights

| Memory Type | Base Weight `T` |
|-------------|-----------------|
| SEMANTIC | 60 |
| EPISODIC | 40 |
| WORKING | 20 |

These weights reflect the documented long-term nature of each memory type.

## 3.5 Importance Formula

```
I = clamp(
        (E * 100)
      + (T * 0.35)
      + (min(R, 10) / 10 * 30)
      + (min(F, 10) / 10 * 10)
      + (A * 5),
      0,
      100
)
```

where `clamp(x, lo, hi)` bounds the result, and

- `E ∈ {0, 1}`
- `T` is the base weight from 3.4
- `R` is the number of active relationships (capped at 10)
- `F` is the retrieval count recorded in retrieval metadata (capped at 10)
- `A` is the normalized age factor:

```
A = 1 / (1 + 0.0005 * age_hours)
```

An explicit user emphasis alone produces at least importance 100 (clamped).

A fresh, unused SEMANTIC memory with no relationships produces approximately 26.

A heavily connected, frequently retrieved SEMANTIC memory approaches 66 before emphasis.

The formula intentionally weights explicit emphasis highest, then relationship density, then type, then usage.

## 3.6 Importance Explanation

Every importance score returns an explanation object:

```json
{
  "score": 64.2,
  "method": "memos.importance.v1",
  "factors": {
    "emphasis": 0,
    "type_weight": 60,
    "relationship_density": 8,
    "retrieval_frequency": 3,
    "age_factor": 0.4
  },
  "last_calculated": "2026-08-06T10:00:00Z"
}
```

## 3.7 Recalculation Triggers

Importance is recalculated when:

- a memory is created
- a relationship is added or removed
- a memory is retrieved
- a memory is updated (new version)
- explicit recalculation is requested

---

# 4. Confidence Scoring

## 4.1 Definition

Confidence estimates the probability that a Memory Object accurately reflects reality.

Confidence measures reliability.

Confidence does not measure usefulness.

## 4.2 Scale

```
0.0
↓
1.0
```

| Range | Meaning |
|-------|---------|
| 0.90–1.00 | Verified |
| 0.70–0.89 | Highly Reliable |
| 0.50–0.69 | Probable |
| 0.30–0.49 | Weak |
| 0.00–0.29 | Unreliable |

## 4.3 Confidence Sources

Confidence may originate from the following sources.

| Source | Base Value |
|--------|-----------|
| `SYSTEM_VERIFIED` | 0.95 |
| `USER_CONFIRMED` | 0.90 |
| `REPEATED_OBSERVATION` | 0.80 |
| `APPLICATION_PROVIDED` | 0.70 |
| `MANUAL_ASSIGNMENT` | caller-provided |
| `INFERRED` | 0.50 |

## 4.4 Confidence Evolution

Confidence may increase through repeated observation.

When a memory is re-observed with the same content, confidence adjusts:

```
C' = min(C + 0.05, 1.0)
```

When contradictory information is recorded, confidence decreases:

```
C' = max(C - 0.15, 0.0)
```

Confidence evolution requires an explicit kernel operation.

Version 1 does not run automatic background confidence updates.

## 4.5 Confidence Explanation

```json
{
  "confidence": 0.8,
  "source": "REPEATED_OBSERVATION",
  "last_updated": "2026-08-06T10:00:00Z"
}
```

---

# 5. Hybrid Retrieval Pipeline

## 5.1 Overview

Retrieval follows the documented hybrid pipeline.

```
Incoming Query
↓
Metadata Filter
↓
Semantic Search
↓
Graph Expansion
↓
Importance Ranking
↓
Confidence Ranking
↓
Permission Validation
↓
Final Ranking
↓
Memory Bundle
```

No single stage determines the final result independently.

## 5.2 Stage 1 — Metadata Filter

Applies mandatory filters before semantic search:

- memory type
- lifecycle state (default `ACTIVE`)
- tags
- owner
- visibility
- namespace
- date range

## 5.3 Stage 2 — Semantic Search

Generates an embedding for the query and retrieves candidate Memory IDs by cosine similarity.

## 5.4 Stage 3 — Graph Expansion

For each semantic candidate, expands along relationships with weight `>= graph_min_weight`.

Relationship types marked as traversable:

```
RELATED_TO
DEPENDS_ON
REFERENCES
FOLLOW_UP
SUPERSEDES
```

`CONTRADICTS` is used as a negative signal, not a traversal edge.

The graph distance is recorded for each candidate.

## 5.5 Stage 4 — Importance Ranking

Each candidate receives its importance score.

## 5.6 Stage 5 — Confidence Ranking

Each candidate receives its confidence score.

## 5.7 Stage 6 — Permission Validation

Candidates that fail permission checks are removed from the result set.

Permission checks always precede final ranking.

## 5.8 Stage 7 — Final Ranking

Candidates are combined into a single final score. See 6.

## 5.9 Stage 8 — Memory Bundle

The top-K results are returned with full explanation metadata.

---

# 6. Retrieval Ranking

## 6.1 Candidate Score

Each candidate Memory Object receives a final score:

```
S = α * sim + β * importance_n + γ * confidence + δ * recency_n + ε * graph_n
```

where:

| Symbol | Meaning | Default |
|--------|---------|---------|
| `sim` | cosine similarity (0..1) | — |
| `importance_n` | normalized importance (`score / 100`) | — |
| `confidence` | confidence (0..1) | — |
| `recency_n` | normalized recency (0..1) | — |
| `graph_n` | graph contribution (0..1) | — |
| `α` | semantic weight | 0.40 |
| `β` | importance weight | 0.30 |
| `γ` | confidence weight | 0.15 |
| `δ` | recency weight | 0.10 |
| `ε` | graph weight | 0.05 |

Weights sum to 1.0.

## 6.2 Recency Normalization

```
recency_n = 1 / (1 + 0.002 * age_hours)
```

## 6.3 Graph Contribution

```
graph_n = 1 / (1 + graph_distance)
```

`graph_distance = 0` for direct semantic matches (contribution 1.0).

## 6.4 Query Without Embedding

If the query is a metadata-only query (no natural language), semantic similarity is omitted and weights are renormalized over the remaining signals.

## 6.5 Explanation Metadata

Every result exposes:

```json
{
  "memory_id": "...",
  "final_score": 0.82,
  "similarity": 0.74,
  "importance": 0.64,
  "confidence": 0.80,
  "recency": 0.9,
  "graph_distance": 1,
  "pathway": ["SEMANTIC", "GRAPH_EXPANSION"],
  "permissions": "ALLOWED"
}
```

---

# 7. Embedding Strategy

## 7.1 Default Provider

Version 1 uses a deterministic local embedding provider.

- no external API
- no model download
- reproducible across restarts
- fixed dimensionality

The provider builds a vocabulary from tokenized text and produces TF-style vectors.

A fixed-dimensional hashed bag-of-words representation is used so no vocabulary state is required after indexing.

## 7.2 Provider Interface

Embedding providers implement:

```python
class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]: ...
    def embed_query(self, text: str) -> list[float]: ...
    @property
    def dimensions(self) -> int: ...
    @property
    def model_name(self) -> str: ...
```

Future providers (Qdrant-hosted models, OpenAI embeddings, sentence-transformers) implement the same interface.

## 7.3 Embedding Versioning

Each embedding records:

- `embedding_id`
- `embedding_model`
- `dimensions`
- `embedding_version`

Changing the embedding provider never changes Memory identity.

---

# 8. Graph Traversal

## 8.1 Neighbor Search

Returns directly related Memory Objects with relationship metadata.

## 8.2 Breadth-First Expansion

Used during retrieval graph expansion.

Limited to `max_depth` (default 2) and `max_nodes` (default 50).

## 8.3 Path Discovery

Used to explain relationship paths between memories.

Returns the shortest path by relationship count.

## 8.4 Cycle Prevention

Circular relationships are rejected at creation time unless the relationship type explicitly permits cycles.

`PARENT_OF` / `CHILD_OF` reject cycles.

---

# 9. Version Management

## 9.1 Version Numbering

Version numbers increase monotonically.

```
1
↓
2
↓
3
```

The latest version is always active.

## 9.2 Immutability

Historical versions are never modified.

A logical update creates a new version with:

- the previous content preserved
- new content stored
- new version number assigned
- `change_reason` recorded

## 9.3 Rollback

Rollback restores a previous version as the active version by creating a new version whose content equals the historical content.

Historical versions are never edited.

---

# 10. Decay Model

## 10.1 Definition

Decay reduces retrieval priority over time.

Decay does not delete memories.

Decay does not alter identity, content, or version history.

## 10.2 Decay Metadata

Version 1 stores decay metadata:

```json
{
  "decay": {
    "last_calculated": "...",
    "base_importance": 62.0,
    "current_importance": 58.4
  }
}
```

## 10.3 Formula

```
current_importance = base_importance * decay_factor
decay_factor = 1 / (1 + 0.0002 * age_hours)
```

## 10.4 Execution

Version 1 does not run automatic decay workers.

Decay is applied during retrieval ranking via the recency signal and exposed through importance recalculation.

Automatic scheduled decay is deferred to Version 2.

---

# 11. Determinism Guarantees

## 11.1 Reproducibility

All scoring functions are pure functions of their inputs.

No random number generation occurs inside the kernel.

## 11.2 Ordering

Result ordering is fully determined by the final score.

Ties are broken by memory ID in ascending order to guarantee stability.

## 11.3 No LLM Dependency

No algorithm in this document invokes a language model.

---

# 12. Conclusion

This document defines the complete algorithmic foundation for MemOS Version 1.

The importance formula, confidence model, hybrid retrieval pipeline, ranking formula, embedding strategy, graph traversal, and version management rules together implement the theoretical framework established in MemoryTheory.md and satisfy the requirements defined in SRS.md.

All algorithms are deterministic, explainable, storage-independent, and model-independent.
