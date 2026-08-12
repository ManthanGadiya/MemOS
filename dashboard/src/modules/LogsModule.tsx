import { useCallback, useState } from "react";
import { api } from "../api/client";
import type { AuditLogPage } from "../api/types";
import {
  EmptyState,
  ErrorBox,
  formatTime,
  Panel,
  ResultBadge,
  Spinner,
} from "../components/ui";
import { useAsync } from "../hooks";

const PAGE_SIZE = 50;

interface Filters {
  operation: string;
  result: string;
}

export function LogsModule() {
  const [filters, setFilters] = useState<Filters>({ operation: "", result: "" });
  const [offset, setOffset] = useState(0);

  const loader = useCallback(() => {
    return api.getLogs({
      operation: filters.operation || undefined,
      result: filters.result || undefined,
      limit: PAGE_SIZE,
      offset,
    });
  }, [filters, offset]);

  const { data, loading, error, reload } = useAsync<AuditLogPage>(loader);

  return (
    <Panel
      title="Logs"
      actions={
        <div className="btn-row">
          <select
            aria-label="Operation"
            value={filters.operation}
            onChange={(event) =>
              setFilters((current) => ({ ...current, operation: event.target.value }))
            }
          >
            <option value="">All operations</option>
            <option value="create">create</option>
            <option value="read">read</option>
            <option value="list">list</option>
            <option value="search">search</option>
            <option value="update">update</option>
            <option value="delete">delete</option>
            <option value="archive">archive</option>
            <option value="restore">restore</option>
            <option value="touch">touch</option>
            <option value="reindex">reindex</option>
            <option value="add_relationship">add_relationship</option>
            <option value="remove_relationship">remove_relationship</option>
            <option value="get_relationships">get_relationships</option>
            <option value="traverse">traverse</option>
            <option value="rollback">rollback</option>
          </select>
          <select
            aria-label="Result"
            value={filters.result}
            onChange={(event) =>
              setFilters((current) => ({ ...current, result: event.target.value }))
            }
          >
            <option value="">All results</option>
            <option value="SUCCESS">SUCCESS</option>
            <option value="FAILURE">FAILURE</option>
            <option value="ROLLBACK">ROLLBACK</option>
            <option value="DENIED">DENIED</option>
          </select>
          <button type="button" className="btn btn--small" onClick={reload}>
            Refresh
          </button>
        </div>
      }
    >
      {loading && <Spinner label="Loading audit log…" />}
      {error && <ErrorBox error={error} />}
      {data && data.records.length === 0 && (
        <EmptyState message="No audit records match the current filters." />
      )}
      {data && data.records.length > 0 && (
        <>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Operation</th>
                  <th>Result</th>
                  <th>Principal</th>
                  <th>Memory ID</th>
                  <th>Request ID</th>
                </tr>
              </thead>
              <tbody>
                {data.records.map((record, index) => (
                  <tr key={`${record.request_id}-${index}`}>
                    <td className="mono">{formatTime(record.timestamp)}</td>
                    <td className="mono">{record.operation}</td>
                    <td>
                      <ResultBadge result={record.result} />
                    </td>
                    <td className="mono">{record.principal_id}</td>
                    <td className="mono">{record.memory_id ?? "—"}</td>
                    <td className="mono muted">{record.request_id.slice(0, 12)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pagination">
            <button
              type="button"
              className="btn btn--small"
              disabled={offset === 0}
              onClick={() => setOffset((current) => Math.max(0, current - PAGE_SIZE))}
            >
              Previous
            </button>
            <span>
              {offset + 1}–{offset + data.records.length} of {data.total}
            </span>
            <button
              type="button"
              className="btn btn--small"
              disabled={offset + data.records.length >= data.total}
              onClick={() => setOffset((current) => current + PAGE_SIZE)}
            >
              Next
            </button>
          </div>
        </>
      )}
    </Panel>
  );
}