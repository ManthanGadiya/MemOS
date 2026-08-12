import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { MemoryObject, MemoryVersion } from "../api/types";
import {
  EmptyState,
  ErrorBox,
  formatTime,
  JsonBlock,
  Panel,
  Spinner,
} from "../components/ui";
import { useAsync } from "../hooks";

export function VersionsModule() {
  const [memoryId, setMemoryId] = useState("");
  const [versions, setVersions] = useState<MemoryVersion[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<MemoryVersion | null>(null);
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
    setSelectedVersion(null);
    api
      .listVersions(memoryId)
      .then(setVersions)
      .catch((cause: Error) => setError(cause))
      .finally(() => setLoading(false));
  }, [memoryId]);

  return (
    <Panel
      title="Version History"
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
      {loading && <Spinner label="Loading versions…" />}
      {error && <ErrorBox error={error} />}
      {!loading && !error && versions.length === 0 && (
        <EmptyState message="No version history for this memory." />
      )}
      {!loading && !error && versions.length > 0 && (
        <>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Version</th>
                  <th>Change</th>
                  <th>Created</th>
                  <th>Content</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {versions.map((version) => (
                  <tr key={version.version}>
                    <td className="mono">v{version.version}</td>
                    <td className="mono">{version.change_type}</td>
                    <td className="mono">{formatTime(version.created_at)}</td>
                    <td>
                      <div className="cell-content">{version.content}</div>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn--small"
                        onClick={() => setSelectedVersion(version)}
                      >
                        Inspect
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {selectedVersion && (
            <div className="mt-16">
              <h3 className="detail-title">
                v{selectedVersion.version} — {selectedVersion.change_type}
              </h3>
              <JsonBlock value={selectedVersion.diff} />
            </div>
          )}
        </>
      )}
    </Panel>
  );
}