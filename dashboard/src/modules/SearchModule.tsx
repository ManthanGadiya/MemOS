import { useState } from "react";
import { api } from "../api/client";
import type { SearchResult } from "../api/types";
import {
  EmptyState,
  ErrorBox,
  formatScore,
  Panel,
  Spinner,
  StateBadge,
  TypeBadge,
} from "../components/ui";

export function SearchModule() {
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(10);
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const runSearch = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      setResults(await api.search({ query, top_k: topK }));
    } catch (cause) {
      setError(cause as Error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Panel
      title="Search"
      actions={
        <div className="btn-row">
          <input
            aria-label="Top K"
            type="number"
            min={1}
            max={100}
            value={topK}
            onChange={(event) => setTopK(Number(event.target.value))}
            style={{ width: 80 }}
          />
          <button
            type="button"
            className="btn btn--primary"
            disabled={loading || !query.trim()}
            onClick={runSearch}
          >
            {loading ? "Searching…" : "Search"}
          </button>
        </div>
      }
    >
      <div className="field">
        <label htmlFor="search-query">Query</label>
        <input
          id="search-query"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void runSearch();
          }}
          placeholder="Natural language query…"
        />
      </div>
      {loading && <Spinner label="Running hybrid retrieval…" />}
      {error && <ErrorBox error={error} />}
      {!loading && !error && results === null && (
        <EmptyState message="Run a query to inspect hybrid retrieval results." />
      )}
      {!loading && !error && results && results.length === 0 && (
        <EmptyState message="No results matched the query." />
      )}
      {!loading && !error && results && results.length > 0 && (
        <div className="table-wrap mt-8">
          <table className="data-table">
            <thead>
              <tr>
                <th>Score</th>
                <th>Sim</th>
                <th>Importance</th>
                <th>Recency</th>
                <th>Graph</th>
                <th>Memory</th>
                <th>State</th>
              </tr>
            </thead>
            <tbody>
              {results.map((result) => (
                <tr key={result.memory.memory_id}>
                  <td className="mono">{formatScore(result.score)}</td>
                  <td className="mono muted">{formatScore(result.similarity)}</td>
                  <td className="mono muted">{formatScore(result.importance)}</td>
                  <td className="mono muted">{formatScore(result.recency)}</td>
                  <td className="mono muted">{formatScore(result.graph_connectivity)}</td>
                  <td>
                    <div className="cell-content">
                      {result.memory.title || result.memory.content}
                    </div>
                    <div className="mono muted">{result.memory.memory_id}</div>
                  </td>
                  <td>
                    <StateBadge state={result.memory.state} />
                    <TypeBadge type={result.memory.type} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
