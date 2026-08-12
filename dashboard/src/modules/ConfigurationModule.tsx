import { useCallback } from "react";
import { api } from "../api/client";
import type { Config } from "../api/types";
import { ErrorBox, Panel, Spinner } from "../components/ui";
import { useAsync } from "../hooks";

export function ConfigurationModule() {
  const loader = useCallback(() => api.getConfig(), []);
  const { data, loading, error, reload } = useAsync<Config>(loader);

  return (
    <Panel
      title="Configuration"
      actions={
        <button type="button" className="btn btn--small" onClick={reload}>
          Refresh
        </button>
      }
    >
      {loading && <Spinner label="Loading configuration…" />}
      {error && <ErrorBox error={error} />}
      {data && (
        <dl className="kv-table">
          {Object.entries(data).map(([key, value]) => (
            <div key={key} style={{ display: "contents" }}>
              <dt>{key}</dt>
              <dd>{String(value)}</dd>
            </div>
          ))}
        </dl>
      )}
    </Panel>
  );
}