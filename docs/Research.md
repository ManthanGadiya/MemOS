# Research Specification

**Project:** MemOS (Memory Operating System)
**Document Version:** 1.0
**Status:** Draft
**Document Type:** Research Specification
**Related Documents**

- PRD.md
- SRS.md
- MemoryTheory.md
- SystemArchitecture.md
- Database.md
- Algorithms.md
- API.md
- MCP.md
- Benchmark.md
- Roadmap.md

---

# 1. Research Objectives

MemOS explores several open research problems in AI memory operating systems. This document catalogs the research questions, hypotheses, and experimental frameworks being investigated.

## 1.1 Hybrid Retrieval Effectiveness

**Question:** How do metadata filtering, vector similarity, graph traversal, importance ranking, and confidence ranking interact to produce retrievable results?

**Hypothesis:** The hybrid pipeline produces significantly higher Precision@K and Recall@K than any single method alone, with graph expansion providing the most marginal gain in Version 1's ~1,000 memory scope.

**Experimental Framework:**

| Metric | Method | Expected Outcome |
|--------|--------|------------------|
| Precision@K | Vector only | Baseline |
| Precision@K | Metadata only | ~40% of vector |
| Precision@K | Hybrid (full pipeline) | > vector only + metadata only |
| Recall@K | Graph expansion depth 1 | +15% over vector only |
| Recall@K | Graph expansion depth 2 | +25% over vector only |
| NDCG | Full pipeline vs ranked similarity | Improved rank discrimination |

**Success Criteria (Phase 1):** Empirical measurement of all five metrics above with Version 1's in-memory stores.

## 1.2 Importance Score Determinism Across Rests

**Question:** Do importance scores remain stable when memories are reloaded from storage, or do floating-point round trips alter scores?

**Hypothesis:** Importance scores are fully deterministic because they depend only on immutable metadata (type, relationship count, retrieval count, explicit emphasis) and the age factor computed from timestamps, which round-trip cleanly through SQLite's DATETIME type.

**Experimental Framework:**

1. Create 50 memories with varying types, tags, relationship counts, and retrieval counts
2. Record importance scores
3. Delete and re-create memories from SQLite (full round-trip)
4. Compare scores before/after
5. Verify `score_before == score_after` for all memories

**Success Criteria:** 100% score preservation across round-trips.

## 1.3 Lifecycle State Interaction with Retrieval

**Question:** How do ARCHIVED and DELETED states interact with the five-stage retrieval pipeline (metadata filter → semantic search → graph expansion → importance → confidence → permission → final ranking)?

**Hypothesis:** 
- Default `ACTIVE` lifecycle filter excludes ARCHIVED memories from semantic/metadata/graph searches
- Explicit `state=ARCHIVED` includes ARCHIVED memories but they receive lower final scores due to recency penalty
- DELETED memories are never returned, even with `state=DELETED` (SRS LC-004)

**Experimental Framework:**

1. Create memories in CREATED → ACTIVE → ARCHIVED → DELETED states
2. Run retrieval at each state transition
3. Record whether memory appears in results
4. Run with explicit `state` parameters (ACTIVE, ARCHIVED, DELETED)
5. Record permission denial counts

**Success Criteria:** 
- Default search never returns DELETED memories
- Default search never returns ARCHIVED memories (unless `state=ARCHIVED`)
- `state=DELETED` still excludes DELETED memories (SRS LC-004)

## 1.4 Confidence Source Resolution Determinism

**Question:** When multiple confidence sources are present in memory metadata, does the resolution order produce consistent results?

**Hypothesis:** The resolution order (metadata confidence_source → stored confidence → default memory.confidence) is deterministic and produces exactly one valid confidence value per memory.

**Experimental Framework:**

1. Create memories with various confidence source combinations
2. Systematically remove each source level
3. Record the resolved confidence and its source label
4. Verify the resolution order matches Algorithms.md §4.3

**Success Criteria:** Every combination resolves to exactly one confidence value following the documented priority.

## 1.5 Relationship Density Counting Methods

**Question:** How does the importance engine count relationships when metadata stores different representations (relationship_count field vs. relationships collection vs. no count)?

**Hypothesis:** The importance engine's `_resolve_relationship_density` function correctly handles all three metadata representations and falls back gracefully when none are present.

**Experimental Framework:**

1. Create memories with `relationship_count` in metadata
2. Create memories with `relationships` collection in metadata
3. Create memories with neither
4. Run importance computation on each
5. Verify the counted R value matches expectations

**Success Criteria:** All three representations produce valid importance scores; the none case defaults to R=0.

## 1.6 Graph Traversal Depth Impact on Retrieval Quality

**Question:** Does increasing graph traversal depth beyond 1 provide diminishing returns for retrieval quality in Version 1's memory volume (~1,000)?

**Hypothesis:** Depth 1 provides ~80% of potential graph expansion benefit; depth 2 provides ~95%; depth 3+ provides <2% additional benefit, making depth 2 the practical ceiling for Version 1.

**Experimental Framework:**

1. Run retrieval with graph_expansion=True and depths 1, 2, 3
2. Measure Precision@K, Recall@K, NDCG for each depth
3. Compare against no graph expansion
4. Measure average candidates per query at each depth

**Success Criteria:** Empirical data showing the depth-benefit curve.

## 1.7 Metadata-Only Query Ranking

**Question:** When a query has no natural language component (metadata-only), how does the weight renormalization affect result quality compared to vector+metadata queries?

**Hypothesis:** Metadata-only queries produce reasonable results for keyword-driven use cases but have lower overall discrimination than vector+metadata queries, with the weight shift (α→0) causing importance/confidence/recency/graph to dominate.

**Experimental Framework:**

1. Run `metadata_only=True` searches with various tag/owner/type filters
2. Run equivalent searches with vector embeddings
3. Compare Precision@K, score distributions
4. Measure edge cases (no matching tags, empty results)

**Success Criteria:** Metadata-only searches return results when vector searches fail, with documented trade-offs.

---

# 2. Research Infrastructure

## 2.1 Benchmark Suite

A benchmark suite should be developed to measure the research objectives above. The suite should:

- Generate deterministic memory collections with controlled properties
- Run each retrieval mode (vector, metadata, hybrid, graph-expanded)
- Record all metrics listed in each research section
- Output results in a machine-readable format (JSON/CSV)
- Support replay for regression testing

**Deliverable:** `scripts/research_benchmark.py` (or similar) that can be run against any MemOS kernel instance.

## 2.2 Data Generation Scripts

Script to create memory collections with known importance characteristics:

- Uniform distribution of types (SEMANTIC/EPISODIC/WORKING)
- Controlled relationship counts (0-10)
- Controlled retrieval counts (0-10)
- Controlled explicit emphasis (present/absent)
- Controlled confidence sources

**Deliverable:** `scripts/generate_test_memories.py`

---

# 3. Version 1 Research Gaps (Deferred to Phase 2+)

The following research problems are acknowledged but deferred beyond Version 1:

| Problem | Reason for Deferral |
|---------|---------------------|
| LLM-assisted importance scoring | Version 1 explicitly avoids LLM dependency (AL-004, AG-004) |
| Automatic importance decay workers | Scheduled background jobs deferred to V2 (Algorithms.md §10.4) |
| Memory consolidation merging | Requires cross-memory analysis beyond V1 scope |
| Multi-agent memory conflict resolution | Version 1 assumes single-user local-first deployment |
| Cloud synchronization | Storage abstraction not yet distributed |
| Adaptive retrieval ranking | Fixed weights in V1; adaptive strategies for V4 |
| Knowledge abstraction (information→memory→knowledge) | Conceptual framework for future versions |
| Memory compression with semantic guarantees | Requires new algorithmic research |

---

# 4. Planned Research Publications

MemOS research contributions intended for academic or community venues:

1. "Hybrid Retrieval in AI Memory Operating Systems" - combining metadata, vector, and graph search
2. "Deterministic Importance Scoring without Language Models" - the importance formula philosophy
3. "Explainable Lifecycle-Aware Retrieval" - how lifecycle states affect retrieval explainability
4. "Version 1 Memory Object Model: From Principles to Implementation" - formal document of the MoO model

---

# 5. Future Research Directions (Phase 2-4)

| Phase | Research Area | Key Questions |
|-------|-------------|--------------|
| V2 | Adaptive Importance | How does importance evolve with task success and user feedback? |
| V2 | Memory Decay | Automatic decay modeling and consolidation |
| V2 | Reflection Engine | Periodic analysis for redundancy detection and pattern discovery |
| V3 | Distributed Retrieval | Consensus across kernels; event-driven synchronization |
| V3 | Multi-Agent Memory | Namespace isolation; shared vs private memories |
| V4 | Knowledge Abstraction | Information → memory → knowledge hierarchy |
| V4 | Predictive Retrieval | Proactive memory presentation based on task context |
| V4 | Memory Com.sleep(20)  # Wait for the outline to appear
    
    found_boxes = []
    # Detect the bar
    box = find_box(image, "hsv_range_bar", min_keypoints=4, threshold=0.3)
    if(memory.get('keep_last_width')):
        width = last_width
    else:
        #print(f"Bar width: {box.w}x{box.h} color={box.color}")
        width = int(max(1, box.w * 0.6))
        last_width = width
    else:
        width = last_width
    
    # Determine color based on width
    #print("width", width)
    #print("last_width", last_width)
    color = get_color_by_width(width)
    #print("Color:", color)
    # Draw the outline
    #console.clear()
    #tcod.console_set_default_foreground(0, color)
    #tcod.console_draw_rect(console, memory.get('x_off', 0), memory.get('y_off', 0), memory.get('w', 100), memory.get('h', 50), tcod.const.TK_DRAW_MODE_DIFF)
    #memory.put('width', width)
    #memory.put('color', color)
    
    if memory.get('is_last'):
        print(f"[INFO] Drawing last {len(found_boxes)} bar(s)...")
    
    # Draw found bars
    for box in found_boxes:
        #print(f"Drawing bar at {memory.get('x_off', 0)}, {memory.get('y_off', 0)} size {memory.get('w', 100)}x{memory.get('h', 50)} color={color}")
        #tcod.console_set_default_foreground(console, color)
        #tcod.console_set_default_background(console, tcod.Color.black)
        #tcod.console_set_default_foreground(console, color)
        #tcod.console_draw_rect(console, memory.get('x_off', 0), memory.get('y_off', 0), memory.get('w', 100), memory.get('h', 50), tcod.console.TK_DRAW_MODE_DIFF)
        pass
    
    print(f"Total bars found: {len(found_boxes)}")
    #print(f"Boxes: {found_boxes}")
    
    # Return the image for display
    return image