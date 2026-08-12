"""Generate a deterministic MemOS memory collection with controlled properties.

Implements the data-generation deliverable of ``docs/Research.md`` section 2.2.

The script produces a **manifest** (JSON) that fully describes the collection:
every memory's controlled properties (type, relationship count, retrieval count,
explicit emphasis, confidence source) plus the benchmark queries and their
ground-truth relevant memory IDs. The manifest is replayable -- any script can
rebuild the identical collection from it, which is what ``research_benchmark.py``
does for regression testing.

Controlled distributions (per Research.md 2.2):
  * Types: uniform SEMANTIC / EPISODIC / WORKING
  * Relationship counts: 0..relationship_max (default 10)
  * Retrieval counts:    0..retrieval_max    (default 10)
  * Explicit emphasis:    present ~30% / absent
  * Confidence sources:   the fixed Algorithms.md 4.3 table

In addition to the per-topic members, the generator adds **graph-only** memories:
memories that belong to a topic (so they are ground-truth-relevant to that topic's
query) but contain no topic keyword and have low semantic similarity to it. They
are reachable *only* via graph traversal from a topic member, which lets the
benchmark measure the recall lift of graph expansion (Research 1.1 / 1.6).

Usage:
    python scripts/generate_test_memories.py --out manifest.json --count 200 --seed 42
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

# Make the ``memos`` package importable when the script is run from backend/.
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_SRC = SCRIPT_DIR.parent / "src"
sys.path.insert(0, str(BACKEND_SRC))

from memos.domain.memory import (  # noqa: E402
    LifecycleState,
    MemoryObject,
    MemoryType,
    PermissionLevel,
    RelationshipType,
)

# Ten distinct topics; the topic phrase is embedded verbatim in every topic
# member so both vector and metadata retrieval can recover it.
TOPICS: List[str] = [
    "quantum entanglement",
    "climate change mitigation",
    "deep neural networks",
    "stock market volatility",
    "ancient roman history",
    "molecular biology basics",
    "space exploration missions",
    "renewable energy storage",
    "cognitive psychology",
    "distributed blockchain systems",
]

FILLERS: List[str] = [
    "Field notes captured during the observation window.",
    "A supplementary remark recorded for later review.",
    "Context gathered from the surrounding environment.",
    "An aside logged while the primary task ran.",
    "A detail worth surfacing in the next retrieval pass.",
]

# Generic content used for graph-only memories: no topic keyword, so it is not
# recoverable via vector similarity or metadata keyword search.
GRAPH_ONLY_FILLERS: List[str] = [
    "A background aside kept for context but never surfaced by keyword search.",
    "An incidental observation recorded without explicit topic markers.",
    "Contextual scaffolding that only a graph walk would surface.",
    "A loosely related note maintained for associative recall.",
]

# Confidence source labels from Algorithms.md 4.3. MANUAL_ASSIGNMENT additionally
# requires an explicit ``confidence`` value.
CONFIDENCE_SOURCES: List[str] = [
    "SYSTEM_VERIFIED",
    "USER_CONFIRMED",
    "REPEATED_OBSERVATION",
    "APPLICATION_PROVIDED",
    "INFERRED",
    "MANUAL_ASSIGNMENT",
]
MANUAL_CONFIDENCE = 0.42

MEMORY_TYPES = [MemoryType.SEMANTIC, MemoryType.EPISODIC, MemoryType.WORKING]


@dataclass
class MemorySpec:
    memory_id: str
    content: str
    title: str
    owner_id: str
    memory_type: str
    permission: str
    state: str
    tags: List[str]
    metadata: Dict[str, Any]
    topic: int
    created_at: str = ""
    last_accessed_at: str = ""
    graph_only: bool = False


@dataclass
class QuerySpec:
    query: str
    topic: int
    relevant_ids: List[str]


@dataclass
class Manifest:
    schema_version: str = "1.0"
    seed: int = 0
    count: int = 0
    topics: List[str] = field(default_factory=list)
    confidence_sources: List[str] = field(default_factory=list)
    relationship_max: int = 2
    retrieval_max: int = 10
    graph_only_per_topic: int = 5
    memories: List[MemorySpec] = field(default_factory=list)
    queries: List[QuerySpec] = field(default_factory=list)
    edges: List[List[str]] = field(default_factory=list)


def _metadata(rng: random.Random, csource: str) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {
        "retrieval_count": rng.randint(0, 10),
        "emphasis": rng.random() < 0.3,
        "confidence_source": csource,
    }
    if csource == "MANUAL_ASSIGNMENT":
        metadata["confidence"] = MANUAL_CONFIDENCE
    return metadata


def generate(
    seed: int,
    count: int,
    relationship_max: int,
    retrieval_max: int,
    graph_only_per_topic: int,
) -> Manifest:
    """Build a fully deterministic collection from ``seed``."""
    rng = random.Random(seed)
    n_topics = len(TOPICS)
    base_time = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    memories: List[MemorySpec] = []

    # ---- Topic members (keyword/semantically recoverable) ----
    for i in range(count):
        topic = i % n_topics
        mtype = MEMORY_TYPES[i % len(MEMORY_TYPES)]
        csource = rng.choice(CONFIDENCE_SOURCES)
        owner_id = f"agent-{i % 3}"
        phrase = TOPICS[topic]
        content = f"{phrase}. {rng.choice(FILLERS)}"
        memory_id = f"mem-{i:05d}"
        created = (base_time + timedelta(hours=i)).isoformat()
        memories.append(
            MemorySpec(
                memory_id=memory_id,
                content=content,
                title=f"note {i}",
                owner_id=owner_id,
                memory_type=mtype.name,
                permission=PermissionLevel.PRIVATE.name,
                state=LifecycleState.ACTIVE.name,
                tags=[f"topic-{topic}"],
                metadata=_metadata(rng, csource),
                topic=topic,
                created_at=created,
                last_accessed_at=created,
            )
        )

    edges: List[List[str]] = []

    # Intra-topic edges (graph structure among members of the same topic).
    ids_by_topic = {
        t: [m.memory_id for m in memories if m.topic == t] for t in range(n_topics)
    }
    for m in memories:
        planned = rng.randint(0, relationship_max)
        peers = [x for x in ids_by_topic[m.topic] if x != m.memory_id]
        if peers:
            for peer in rng.sample(peers, min(planned, len(peers))):
                edges.append([m.memory_id, peer, RelationshipType.RELATED_TO.name])

    # ---- Graph-only memories (reachable only via graph traversal) ----
    for t in range(n_topics):
        members = [m.memory_id for m in memories if m.topic == t]
        # Sample UNIQUE members as go sources to keep degree bounded.
        # Each member is the source for at most one go, ensuring
        # graph-only candidates have connectivity ≤ 0.5 (no high-degree
        # distractors outrank them).
        unique_sources = rng.sample(members, min(len(members), graph_only_per_topic))
        for j in range(graph_only_per_topic):
            memory_id = f"go-{t:02d}-{j:03d}"
            csource = rng.choice(CONFIDENCE_SOURCES)
            content = (
                f"{rng.choice(GRAPH_ONLY_FILLERS)} (topic {t}, index {j})"
            )
            created = (base_time + timedelta(hours=count + t * 100 + j)).isoformat()
            go = MemorySpec(
                memory_id=memory_id,
                content=content,
                title=f"go {t}-{j}",
                owner_id=f"agent-{j % 3}",
                memory_type=MEMORY_TYPES[j % 3].name,
                permission=PermissionLevel.PRIVATE.name,
                state=LifecycleState.ACTIVE.name,
                tags=[],
                metadata=_metadata(rng, csource),
                topic=t,
                created_at=created,
                last_accessed_at=created,
                graph_only=True,
            )
            memories.append(go)
            # Link from a unique topic member so graph expansion can reach it.
            # Each member serves as source for at most one go.
            edges.append(
                [unique_sources[j], memory_id, RelationshipType.RELATED_TO.name]
            )

    # Reconcile relationship_count from the actual out-degree so the importance
    # engine (which reads relationship_count from metadata) matches the graph.
    out_degree = Counter(edge[0] for edge in edges)
    for m in memories:
        m.metadata["relationship_count"] = out_degree.get(m.memory_id, 0)

    queries = [
        QuerySpec(
            query=TOPICS[t],
            topic=t,
            relevant_ids=[m.memory_id for m in memories if m.topic == t],
        )
        for t in range(n_topics)
    ]

    return Manifest(
        seed=seed,
        count=count,
        topics=TOPICS,
        confidence_sources=CONFIDENCE_SOURCES,
        relationship_max=relationship_max,
        retrieval_max=retrieval_max,
        graph_only_per_topic=graph_only_per_topic,
        memories=memories,
        queries=queries,
        edges=edges,
    )


def summarize(manifest: Manifest) -> str:
    type_counts = Counter(m.memory_type for m in manifest.memories)
    rel_counts = Counter(m.metadata.get("relationship_count", 0) for m in manifest.memories)
    emph = sum(1 for m in manifest.memories if m.metadata.get("emphasis"))
    conf = Counter(m.metadata.get("confidence_source") for m in manifest.memories)
    go = sum(1 for m in manifest.memories if m.graph_only)
    lines = [
        f"seed={manifest.seed} count={manifest.count} topics={len(manifest.topics)}",
        f"graph_only_memories={go} edges={len(manifest.edges)}",
        f"types: {dict(type_counts)}",
        f"emphasis present: {emph}/{manifest.count}",
        f"relationship_count distribution: {dict(sorted(rel_counts.items()))}",
        f"confidence sources: {dict(conf.items())}",
        f"avg relevant per query: "
        f"{sum(len(q.relevant_ids) for q in manifest.queries) / max(1, len(manifest.queries)):.1f}",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="manifest.json", help="Output manifest path")
    parser.add_argument("--count", type=int, default=200, help="Number of topic members")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--relationship-max", type=int, default=10)
    parser.add_argument("--retrieval-max", type=int, default=10)
    parser.add_argument("--graph-only-per-topic", type=int, default=5)
    args = parser.parse_args()

    manifest = generate(
        seed=args.seed,
        count=args.count,
        relationship_max=args.relationship_max,
        retrieval_max=args.retrieval_max,
        graph_only_per_topic=args.graph_only_per_topic,
    )

    out_path = Path(args.out)
    out_path.write_text(json.dumps(asdict(manifest), indent=2), encoding="utf-8")

    print(summarize(manifest))
    print(f"\nManifest written to: {out_path.resolve()}")


if __name__ == "__main__":
    main()
