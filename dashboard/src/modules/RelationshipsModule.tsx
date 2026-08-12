import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { MemoryObject, Relationship } from "../api/types";
import {
  EmptyState,
  ErrorBox,
  formatTime,
  Panel,
  Spinner,
} from "../components/ui";
import { useAsync } from "../hooks";

export function RelationshipsModule() {
  const [memoryId, setMemoryId] = useState("");
  const [relationships, setRelationships] = useState<Relationship[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const loader = useCallback(() => api.listMemories({ limit: 100 }), []);
  const list = useAsync<MemoryObject[]>(loader);

  useEffect(() => {
    if (list.data && list.data.length > 0 && memoryId === "") {
      setMemoryId(list.data[0].memory_id);
    }
  }, [list.data, memoryId]);

  useEffect(() => {
    if (!memoryId) return;
    setLoading(true);
    setError(null);
    api
      .getRelated(memoryId)
      .then(setRelationships)
      .catch((cause: Error) => setError(cause))
      .finally(() => setLoading(false));
  }, [memoryId]);

  const remove = async (relationshipId: string) => {
    if (!window.confirm("Delete this relationship?")) return;
    try {
      await api.deleteRelationship(memoryId, relationshipId);
      setRelationships((current) =>
        current.filter((relationship) => relationship.relationship_id !== relationshipId),
      );
    } catch (cause) {
      setError(cause as Error);
    }
  };

  return (
    <Panel
      title="Relationship Viewer"
      actions={
        <select
          aria-label="Memory"
          value={memoryId}
          onChange={(event) => setMemoryId(event.target.value)}
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
      {!loading && !error && relationships.length === 0 && (
        <EmptyState message="No relationships for this memory." />
      )}
      {!loading && !error && relationships.length > 0 && (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Type</th>
                <th>Source</th>
                <th>Target</th>
                <th>Weight</th>
                <th>Created</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {relationships.map((relationship) => (
                <tr key={relationship.relationship_id}>
                  <td className="mono">{relationship.type}</td>
                  <td className="mono">{relationship.source_id}</td>
                  <td className="mono">{relationship.target_id}</td>
                  <td className="mono">{relationship.weight.toFixed(2)}</td>
                  <td className="mono">{formatTime(relationship.created_at)}</td>
                  <td>
                    <button
                      type="button"
                      className="btn btn--small btn--danger"
                      onClick={() => void remove(relationship.relationship_id)}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <AddRelationshipForm
        sourceId={memoryId}
        onAdded={(relationship) =>
          setRelationships((current) => [...current, relationship])
        }
      />
    </Panel>
  );
}

function AddRelationshipForm({
  sourceId,
  onAdded,
}: {
  sourceId: string;
  onAdded: (relationship: Relationship) => void;
}) {
  const [targetId, setTargetId] = useState("");
  const [relationshipType, setRelationshipType] = useState("related_to");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const submit = async () => {
    if (!targetId.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await api.createRelationship(sourceId, {
        target_id: targetId,
        relationship_type: relationshipType,
      });
      setTargetId("");
      onAdded(created);
    } catch (cause) {
      setError(cause as Error);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mt-16">
      <div className="form-grid">
        <div className="field">
          <label htmlFor="rel-target">Target Memory ID</label>
          <input
            id="rel-target"
            value={targetId}
            onChange={(event) => setTargetId(event.target.value)}
            placeholder="memory_id"
          />
        </div>
        <div className="field">
          <label htmlFor="rel-type">Relationship Type</label>
          <select
            id="rel-type"
            value={relationshipType}
            onChange={(event) => setRelationshipType(event.target.value)}
          >
            <option value="related_to">related_to</option>
            <option value="belongs_to">belongs_to</option>
            <option value="depends_on">depends_on</option>
            <option value="parent_of">parent_of</option>
            <option value="child_of">child_of</option>
            <option value="supersedes">supersedes</option>
            <option value="contradicts">contradicts</option>
            <option value="references">references</option>
            <option value="follow_up">follow_up</option>
          </select>
        </div>
      </div>
      {error && <ErrorBox error={error} />}
      <button
        type="button"
        className="btn btn--primary"
        disabled={submitting || !targetId.trim()}
        onClick={submit}
      >
        {submitting ? "Adding…" : "Add Relationship"}
      </button>
    </div>
  );
}