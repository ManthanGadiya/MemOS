"""MemOS research benchmark suite.

Implements the benchmark deliverable of ``docs/Research.md`` section 2.1.

The suite consumes a manifest produced by ``generate_test_memories.py``
(replay for regression testing), rebuilds the identical collection inside a
``RetrievalEngine`` harness, and measures the research objectives:

  * Section 1.1 / 2.1 -- Hybrid retrieval effectiveness across the four
    retrieval modes (vector, metadata, hybrid, graph-expanded) plus a
    metadata-only mode. Reports Precision@K, Recall@K, NDCG@K averaged over
    the benchmark queries.
  * Section 1.2 -- Importance-score determinism across a reload round-trip.
  * Section 1.4 -- Confidence-source resolution determinism.
  * Section 1.5 -- Relationship-density counting across the three metadata
    representations.

The benchmark drives ``RetrievalEngine`` directly rather than ``MemoryKernel``:
``kernel.search`` only exposes ``graph_expansion`` and cannot select a retrieval
mode or enable ``metadata_only`` (those are engine-level parameters). See the
"API gap" note in the JSON report.

Usage:
    python scripts/research_benchmark.py --manifest manifest.json --out report.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_SRC = SCRIPT_DIR.parent / "src"
sys.path.insert(0, str(BACKEND_SRC))

from memos.config.settings import Settings  # noqa: E402
from memos.domain.memory import (  # noqa: E402
    LifecycleState,
    MemoryObject,
    MemoryType,
    PermissionLevel,
    RelationshipType,
)
from memos.engines import RetrievalEngine  # noqa: E402
from memos.engines.graph import GraphEngine  # noqa: E402
from memos.engines.importance import (  # noqa: E402
    ImportanceEngine,
    _resolve_relationship_density,
)
from memos.engines.permission import PermissionEngine  # noqa: E402
from memos.storage.in_memory_graph import InMemoryGraphStore  # noqa: E402
from memos.storage.in_memory_vector import InMemoryVectorStore  # noqa: E402
from memos.storage.sqlite_metadata import SQLiteMetadataStore  # noqa: E402

KS = [5, 10, 20, 40]
# Tolerance for the unavoidable clock advance between consecutive compute() calls
# (the importance engine reads now_utc() internally, so scores drift by the
# sub-microsecond wall-clock delta between calls).
SCORE_TOLERANCE = 1e-9


# ---------------------------------------------------------------------------
# Benchmark embedder
# ---------------------------------------------------------------------------
# The production ``HashEmbedder`` hashes character *n*-grams, so unrelated
# sentences share coincidental 3-char collisions. That gives every memory a
# small nonzero similarity to any query, which masks the contribution of graph
# traversal (graph-only memories are outranked by weakly-matching noise).
#
# To isolate the graph-expansion variable, the benchmark uses a deterministic
# WORD-token embedder with stopwords removed. Under it, two texts are similar
# only when they share salient vocabulary, so:
#   * a topic's members share the topic phrase with the query  -> high sim
#   * off-topic members share no salient token                -> sim 0
#   * graph-only memories share no salient token              -> sim 0 (only
#     reachable via graph traversal)
# This lets the benchmark cleanly measure each retrieval mode's unique value.
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with",
        "by", "from", "at", "as", "is", "are", "was", "were", "be", "this",
        "that", "these", "those", "it", "its", "later", "review", "recorded",
        "remark", "supplementary", "kept", "context", "background", "aside",
        "never", "surfaced", "keyword", "search", "note", "captured",
        "index", "topic", "only", "graph", "memory", "memories",
    }
)


class WordHashEmbedder:
    """Deterministic word-token embedder for benchmark isolation.

    Tokenizes on non-alphanumeric boundaries, drops stopwords, hashes the
    remaining salient tokens into a high-dimensional signed bag-of-words
    vector, and L2-normalizes. Identical inputs yield identical vectors.
    """

    def __init__(self, dimension: int = 1024) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.dimension = dimension

    def _tokens(self, text: str) -> List[str]:
        lowered = re.sub(r"[^a-z0-9]+", " ", text.lower())
        return [tok for tok in lowered.split() if tok and tok not in _STOPWORDS]

    def embed(self, text: str) -> List[float]:
        vector = np.zeros(self.dimension, dtype=np.float64)
        for tok in self._tokens(text):
            digest = hashlib.sha256(tok.encode("utf-8")).hexdigest()
            index = int(digest[:8], 16) % self.dimension
            sign = 1.0 if int(digest[8:16], 16) % 2 == 0 else -1.0
            vector[index] += sign
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm
        return vector.tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.embed(t) for t in texts]


# ---------------------------------------------------------------------------
# Replay harness
# ---------------------------------------------------------------------------


class BenchmarkHarness:
    """Rebuilds the manifest collection inside fresh stores."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.metadata_store = SQLiteMetadataStore(":memory:")
        self.vector_store = InMemoryVectorStore()
        self.graph_store = InMemoryGraphStore()
        self.embedder = WordHashEmbedder(dimension=1024)
        self.graph_engine = GraphEngine(self.graph_store)
        self.permission_engine = PermissionEngine(settings)
        self.engine = RetrievalEngine(
            metadata_store=self.metadata_store,
            vector_store=self.vector_store,
            graph_engine=self.graph_engine,
            embedder=self.embedder,
            permission_engine=self.permission_engine,
            settings=settings,
        )

    def add(self, memory: MemoryObject) -> None:
        self.metadata_store.create(memory)
        self.vector_store.upsert(
            memory.memory_id, self.embedder.embed(memory.content), {}
        )
        self.graph_store.cache_node(memory)

    def close(self) -> None:
        self.metadata_store.close()


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def reconstruct(spec: Dict[str, Any]) -> MemoryObject:
    return MemoryObject(
        memory_id=spec["memory_id"],
        content=spec["content"],
        title=spec.get("title", ""),
        owner_id=spec.get("owner_id", "default"),
        type=getattr(MemoryType, spec["memory_type"]),
        permission=getattr(PermissionLevel, spec["permission"]),
        state=getattr(LifecycleState, spec["state"]),
        tags=list(spec.get("tags", [])),
        metadata=dict(spec.get("metadata", {})),
        created_at=_parse_dt(spec.get("created_at")),
        last_accessed_at=_parse_dt(spec.get("last_accessed_at")),
    )


def asdict_spec(memory: MemoryObject) -> Dict[str, Any]:
    """Project a MemoryObject back into the manifest spec shape."""
    return {
        "memory_id": memory.memory_id,
        "content": memory.content,
        "title": memory.title,
        "owner_id": memory.owner_id,
        "memory_type": memory.type.name,
        "permission": memory.permission.name,
        "state": memory.state.name,
        "tags": list(memory.tags),
        "metadata": dict(memory.metadata),
        "created_at": memory.created_at.isoformat() if memory.created_at else "",
        "last_accessed_at": (
            memory.last_accessed_at.isoformat() if memory.last_accessed_at else ""
        ),
    }


# ---------------------------------------------------------------------------
# IR metrics
# ---------------------------------------------------------------------------


def precision_at_k(ranked: List[str], relevant: Set[str], k: int) -> float:
    top = ranked[:k]
    if not top:
        return 0.0
    return sum(1 for mid in top if mid in relevant) / len(top)


def recall_at_k(ranked: List[str], relevant: Set[str], k: int) -> float:
    if not relevant:
        return 0.0
    top = ranked[:k]
    return sum(1 for mid in top if mid in relevant) / len(relevant)


def ndcg_at_k(ranked: List[str], relevant: Set[str], k: int) -> float:
    def dcg(ids: List[str]) -> float:
        return sum(
            1.0 / math.log2(i + 2) for i, mid in enumerate(ids) if mid in relevant
        )

    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    if ideal == 0.0:
        return 0.0
    return dcg(ranked[:k]) / ideal


# ---------------------------------------------------------------------------
# Retrieval evaluation (Research 1.1 / 2.1)
# ---------------------------------------------------------------------------


def evaluate_retrieval(harness: BenchmarkHarness, manifest: Dict[str, Any]) -> Dict[str, Any]:
    max_k = max(KS)
    queries = manifest["queries"]

    modes = {
        "vector": lambda q, k: harness.engine.semantic_search(q, top_k=k),
        "metadata": lambda q, k: harness.engine.metadata_search(q, top_k=k),
        "hybrid": lambda q, k: harness.engine.hybrid_search(q, top_k=k),
        "graph_expanded": lambda q, k: harness.engine.hybrid_search(
            q, top_k=k, graph_expansion=True
        ),
        "metadata_only": lambda q, k: harness.engine.hybrid_search(
            q, top_k=k, metadata_only=True
        ),
    }

    retrieval_metrics: Dict[str, Any] = {}
    per_query_rows: List[Dict[str, Any]] = []

    for mode_name, fn in modes.items():
        agg = {k: {"P": [], "R": [], "N": []} for k in KS}
        for q in queries:
            ranked = [item.memory.memory_id for item in fn(q["query"], max_k)]
            relevant = set(q["relevant_ids"])
            for k in KS:
                p = precision_at_k(ranked, relevant, k)
                r = recall_at_k(ranked, relevant, k)
                n = ndcg_at_k(ranked, relevant, k)
                agg[k]["P"].append(p)
                agg[k]["R"].append(r)
                agg[k]["N"].append(n)
                per_query_rows.append(
                    {
                        "mode": mode_name,
                        "query": q["query"],
                        "k": k,
                        "precision": round(p, 4),
                        "recall": round(r, 4),
                        "ndcg": round(n, 4),
                    }
                )
        retrieval_metrics[mode_name] = {
            f"P@{k}": round(statistics.mean(agg[k]["P"]), 4) for k in KS
        }
        for k in KS:
            retrieval_metrics[mode_name][f"R@{k}"] = round(
                statistics.mean(agg[k]["R"]), 4
            )
            retrieval_metrics[mode_name][f"NDCG@{k}"] = round(
                statistics.mean(agg[k]["N"]), 4
            )

    return {
        "metrics": retrieval_metrics,
        "per_query_rows": per_query_rows,
        "query_count": len(queries),
        "max_k": max_k,
    }


# ---------------------------------------------------------------------------
# Importance experiments (Research 1.2 / 1.4 / 1.5)
# ---------------------------------------------------------------------------


def evaluate_importance(manifest: Dict[str, Any]) -> Dict[str, Any]:
    settings = Settings()
    engine = ImportanceEngine(settings)

    # Section 1.2 -- determinism across a reload round-trip.
    #
    # The importance engine is stateless between calls, but it reads now_utc()
    # internally, so two compute() calls differ by the sub-microsecond wall-clock
    # delta. We therefore compare with a small tolerance:
    #   1. Statelessness: compute() twice on the same memory must agree within
    #      tolerance (no hidden accumulation between calls).
    #   2. Round-trip: rebuild an identical memory (same timestamps, as a SQLite
    #      reload would preserve them) and compare within tolerance.
    memories = [reconstruct(m) for m in manifest["memories"]]
    sample = memories[: min(50, len(memories))]
    stateful_mismatches = 0
    roundtrip_mismatches = 0
    examples = []
    for original in sample:
        first = engine.compute(original)
        second = engine.compute(original)
        if abs(first.raw_score - second.raw_score) > SCORE_TOLERANCE:
            stateful_mismatches += 1
        reloaded = engine.compute(reconstruct(asdict_spec(original)))
        if abs(first.raw_score - reloaded.raw_score) > SCORE_TOLERANCE:
            roundtrip_mismatches += 1
            if len(examples) < 5:
                examples.append(
                    {
                        "memory_id": original.memory_id,
                        "score_original": first.raw_score,
                        "score_reloaded": reloaded.raw_score,
                    }
                )

    # Section 1.4 -- confidence-source resolution.
    confidence_rows = []
    for source in manifest.get("confidence_sources", []):
        metadata: Dict[str, Any] = {"confidence_source": source}
        if source == "MANUAL_ASSIGNMENT":
            metadata["confidence"] = 0.42
        mem = MemoryObject(content="confidence probe", metadata=metadata)
        score = engine.compute(mem)
        confidence_rows.append(
            {
                "source_requested": source,
                "source_resolved": score.components["confidence_source"],
                "confidence": score.components["confidence"],
            }
        )

    # Section 1.5 -- relationship-density counting across representations.
    density_rows = []
    for label, metadata in [
        ("relationship_count_field", {"relationship_count": 7}),
        (
            "relationships_collection",
            {"relationships": [{"memory_id": f"x{i}"} for i in range(4)]},
        ),
        ("none", {}),
    ]:
        mem = MemoryObject(content="density probe", metadata=metadata)
        density_rows.append(
            {"representation": label, "resolved_R": _resolve_relationship_density(mem)}
        )

    return {
        "determinism": {
            "sampled": len(sample),
            "stateful_mismatches": stateful_mismatches,
            "roundtrip_mismatches": roundtrip_mismatches,
            "all_equal": stateful_mismatches == 0 and roundtrip_mismatches == 0,
            "examples": examples,
        },
        "confidence_resolution": confidence_rows,
        "relationship_density": density_rows,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="manifest.json")
    parser.add_argument("--out", default="report.json")
    parser.add_argument("--csv", default="retrieval_metrics.csv")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        raise SystemExit(f"Manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    settings = Settings()
    harness = BenchmarkHarness(settings)
    for spec in manifest["memories"]:
        harness.add(reconstruct(spec))
    for source, target, rel in manifest["edges"]:
        harness.graph_engine.add_relationship(
            source, target, getattr(RelationshipType, rel)
        )

    retrieval = evaluate_retrieval(harness, manifest)
    importance = evaluate_importance(manifest)
    harness.close()

    report = {
        "manifest": str(manifest_path.resolve()),
        "collection": {
            "count": manifest["count"],
            "seed": manifest["seed"],
            "topics": len(manifest["topics"]),
            "edges": len(manifest["edges"]),
        },
        "api_gap_note": (
            "kernel.search exposes only graph_expansion; retrieval mode and "
            "metadata_only selection are engine-level, so this benchmark drives "
            "RetrievalEngine directly."
        ),
        "retrieval_metrics": retrieval["metrics"],
        "importance": importance,
    }

    out_path = Path(args.out)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    csv_path = Path(args.csv)
    write_csv(
        csv_path,
        retrieval["per_query_rows"],
        ["mode", "query", "k", "precision", "recall", "ndcg"],
    )

    # Console summary.
    print(f"Collection: {report['collection']}")
    print("\nRetrieval metrics (averaged over queries):")
    header = "mode".ljust(16) + "".join(
        f"{m}@{k}".rjust(10) for m in ("P", "R", "NDCG") for k in KS
    )
    print(header)
    for mode, metrics in retrieval["metrics"].items():
        row = mode.ljust(16)
        for m in ("P", "R", "NDCG"):
            for k in KS:
                row += f"{metrics[f'{m}@{k}']:.3f}".rjust(10)
        print(row)

    det = importance["determinism"]
    print(
        f"\nImportance determinism: {det['sampled']} sampled, "
        f"stateful mismatches={det['stateful_mismatches']}, "
        f"roundtrip mismatches={det['roundtrip_mismatches']} -> "
        f"{'PASS' if det['all_equal'] else 'FAIL'}"
    )
    print(f"Relationship density: {importance['relationship_density']}")

    print(f"\nJSON report: {out_path.resolve()}")
    print(f"CSV metrics: {csv_path.resolve()}")


if __name__ == "__main__":
    main()
