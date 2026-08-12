import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { MemoryObject, Relationship } from "../api/types";
import { EmptyState, ErrorBox, Panel, Spinner } from "../components/ui";
import { useAsync } from "../hooks";

const VIEW_WIDTH = 800;
const VIEW_HEIGHT = 460;
const CENTER_X = VIEW_WIDTH / 2;
const CENTER_Y = VIEW_HEIGHT / 2;
const RADIUS = 170;

const TYPE_COLORS: Record<string, string> = {
  semantic: "#4da3ff",
  episodic: "#2ecc71",
  procedural: "#f1c40f",
  working: "#e74c3c",
};

interface GraphNode {
  id: string;
  label: string;
  color: string;
  x: number;
  y: number;
  isRoot: boolean;
}

interface GraphEdge {
  from: string;
  to: string;
  label: string;
}

export function GraphModule() {
  const [rootId, setRootId] = useState<string>("");
  const [relationships, setRelationships] = useState<Relationship[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const loader = useCallback(() => api.listMemories({ limit: 100 }), []);
  const list = useAsync<MemoryObject[]>(loader);
  const memories = list.data ?? [];

  useEffect(() => {
    if (list.data && list.data.length > 0 && rootId === "") {
      setRootId(list.data[0].memory_id);
    }
  }, [list.data, rootId]);

  useEffect(() => {
    if (!rootId) return;
    setLoading(true);
    setError(null);
    api
      .getRelated(rootId)
      .then(setRelationships)
      .catch((cause: Error) => setError(cause))
      .finally(() => setLoading(false));
  }, [rootId]);

  const nodes = useMemo<GraphNode[]>(() => {
    if (!rootId) return [];
    const byId = new Map(memories.map((memory) => [memory.memory_id, memory]));
    const root = byId.get(rootId);
    const neighbors = Array.from(
      new Set(
        relationships.flatMap((relationship) =>
          relationship.source_id === rootId
            ? [relationship.target_id]
            : [relationship.source_id],
        ),
      ),
    ).filter((id) => id !== rootId);

    const result: GraphNode[] = [];
    if (root) {
      result.push({
        id: root.memory_id,
        label: root.title || root.content.slice(0, 24),
        color: TYPE_COLORS[root.type] ?? "#6b7684",
        x: CENTER_X,
        y: CENTER_Y,
        isRoot: true,
      });
    }
    neighbors.forEach((neighborId, index) => {
      const memory = byId.get(neighborId);
      const angle = (index / neighbors.length) * Math.PI * 2;
      result.push({
        id: neighborId,
        label: memory
          ? memory.title || memory.content.slice(0, 24)
          : neighborId.slice(0, 8),
        color: memory ? TYPE_COLORS[memory.type] ?? "#6b7684" : "#6b7684",
        x: CENTER_X + RADIUS * Math.cos(angle),
        y: CENTER_Y + RADIUS * Math.sin(angle),
        isRoot: false,
      });
    });
    return result;
  }, [memories, relationships, rootId]);

  const edges = useMemo<GraphEdge[]>(
    () =>
      relationships.map((relationship) => ({
        from: relationship.source_id,
        to: relationship.target_id,
        label: relationship.type,
      })),
    [relationships],
  );

  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);

  return (
    <Panel
      title="Graph Viewer"
      actions={
        <select
          aria-label="Root memory"
          value={rootId}
          onChange={(event) => setRootId(event.target.value)}
        >
          {list.data?.map((memory) => (
            <option key={memory.memory_id} value={memory.memory_id}>
              {memory.title || memory.content.slice(0, 40)}
            </option>
          ))}
        </select>
      }
    >
      {list.error && <ErrorBox error={list.error} />}
      {loading && <Spinner label="Loading relationships…" />}
      {error && <ErrorBox error={error} />}
      {!loading && !error && rootId && nodes.length === 0 && (
        <EmptyState message="This memory has no relationships yet." />
      )}
      {!loading && !error && nodes.length > 0 && (
        <>
          <svg
            className="graph-canvas"
            viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
            role="img"
            aria-label="Memory relationship graph"
          >
            {edges.map((edge) => {
              const from = nodeById.get(edge.from);
              const to = nodeById.get(edge.to);
              if (!from || !to) return null;
              const midX = (from.x + to.x) / 2;
              const midY = (from.y + to.y) / 2 - 10;
              return (
                <g key={`${edge.from}-${edge.to}-${edge.label}`}>
                  <line
                    x1={from.x}
                    y1={from.y}
                    x2={to.x}
                    y2={to.y}
                    stroke="#262e38"
                    strokeWidth={1.5}
                  />
                  <text x={midX} y={midY} textAnchor="middle" fontSize={9} fill="#8b96a5">
                    {edge.label}
                  </text>
                </g>
              );
            })}
            {nodes.map((node) => (
              <g
                key={node.id}
                className="graph-node"
                transform={`translate(${node.x}, ${node.y})`}
                onClick={() => setRootId(node.id)}
              >
                <circle
                  r={node.isRoot ? 22 : 14}
                  fill={node.color}
                  fillOpacity={node.isRoot ? 0.95 : 0.55}
                  stroke={node.color}
                  strokeWidth={node.isRoot ? 2 : 1}
                />
                <text y={34} textAnchor="middle">
                  {node.label}
                </text>
              </g>
            ))}
          </svg>
          <p className="muted">Click any node to re-root the graph.</p>
        </>
      )}
    </Panel>
  );
}
