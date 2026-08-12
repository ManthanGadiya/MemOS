import { useCallback } from "react";
import { api } from "../api/client";
import type { Statistics } from "../api/types";
import { ErrorBox, Panel, Spinner, StatCard } from "../components/ui";
import { useAsync } from "../hooks";

export function StatisticsModule() {
  const loader = useCallback(() => api.getStatistics(), []);
  const { data, loading, error, reload } = useAsync<Statistics>(loader);

  return (
    <Panel
      title="Statistics"
      actions={
        <button type="button" className="btn btn--small" onClick={reload}>
          Refresh
        </button>
      }
    >
      {loading && <Spinner label="Loading statistics…" />}
      {error && <ErrorBox error={error} />}
      {data && (
        <div className="stat-grid">
          <StatCard label="Memories" value={data.memory_count} accent="blue" />
          <StatCard label="Relationships" value={data.relationship_count} accent="green" />
          <StatCard label="Audit Entries" value={data.audit_count} accent="yellow" />
        </div>
      )}
    </Panel>
  );
}
