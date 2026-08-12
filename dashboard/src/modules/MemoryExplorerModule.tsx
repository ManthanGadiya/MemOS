import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { MemoryObject } from "../api/types";
import {
  EmptyState,
  ErrorBox,
  formatTime,
  JsonBlock,
  Panel,
  Spinner,
  StateBadge,
  TypeBadge,
} from "../components/ui";
import { useAsync } from "../hooks";

const PAGE_SIZE = 25;

interface Filters {
  state: string;
  memory_type: string;
}

export function MemoryExplorerModule() {
  const [filters, setFilters] = useState<Filters>({ state: "", memory_type: "" });
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<MemoryObject | null>(null);

  const loader = useCallback(() => {
    return api.listMemories({
      state: filters.state || undefined,
      memory_type: filters.memory_type || undefined,
      limit: PAGE_SIZE,
      offset,
    });
  }, [filters, offset]);

  const { data, loading, error, reload } = useAsync<MemoryObject[]>(loader);

  useEffect(() => {
    setOffset(0);
  }, [filters]);

  const openMemory = useCallback(async (memoryId: string) => {
    try {
      setSelected(await api.getMemory(memoryId));
    } catch (cause) {
      setSelected(null);
      reload();
    }
  }, [reload]);

  return (
    <>
      <Panel
        title="Memory Explorer"
        actions={
          <div className="btn-row">
            <select
              aria-label="Lifecycle state"
              value={filters.state}
              onChange={(event) =>
                setFilters((current) => ({ ...current, state: event.target.value }))
              }
            >
              <option value="">All states</option>
              <option value="active">Active</option>
              <option value="archived">Archived</option>
              <option value="deleted">Deleted</option>
            </select>
            <select
              aria-label="Memory type"
              value={filters.memory_type}
              onChange={(event) =>
                setFilters((current) => ({ ...current, memory_type: event.target.value }))
              }
            >
              <option value="">All types</option>
              <option value="semantic">Semantic</option>
              <option value="episodic">Episodic</option>
              <option value="procedural">Procedural</option>
              <option value="working">Working</option>
            </select>
            <button type="button" className="btn btn--small" onClick={reload}>
              Refresh
            </button>
          </div>
        }
      >
        {loading && <Spinner label="Loading memories…" />}
        {error && <ErrorBox error={error} />}
        {data && data.length === 0 && (
          <EmptyState message="No memories match the current filters." />
        )}
        {data && data.length > 0 && (
          <>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Title / Content</th>
                    <th>Type</th>
                    <th>State</th>
                    <th>Importance</th>
                    <th>Version</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {data.map((memory) => (
                    <tr key={memory.memory_id} onClick={() => openMemory(memory.memory_id)}>
                      <td>
                        <div className="cell-content">
                          {memory.title || memory.content}
                        </div>
                        <div className="mono muted">{memory.memory_id}</div>
                      </td>
                      <td>
                        <TypeBadge type={memory.type} />
                      </td>
                      <td>
                        <StateBadge state={memory.state} />
                      </td>
                      <td className="mono">
                        {memory.importance.toFixed(1)}
                        <span className="muted"> {memory.importance_category}</span>
                      </td>
                      <td className="mono">v{memory.version}</td>
                      <td className="mono">{formatTime(memory.updated_at)}</td>
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
                {offset + 1}–{offset + data.length}
              </span>
              <button
                type="button"
                className="btn btn--small"
                disabled={data.length < PAGE_SIZE}
                onClick={() => setOffset((current) => current + PAGE_SIZE)}
              >
                Next
              </button>
            </div>
          </>
        )}
      </Panel>

      <CreateMemoryPanel onCreated={reload} />
      {selected && (
        <MemoryDetailPanel
          memory={selected}
          onChanged={(updated) => setSelected(updated)}
          onDeleted={() => {
            setSelected(null);
            reload();
          }}
        />
      )}
    </>
  );
}

function CreateMemoryPanel({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [content, setContent] = useState("");
  const [title, setTitle] = useState("");
  const [tags, setTags] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const submit = async () => {
    if (!content.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.createMemory({
        content,
        title: title || undefined,
        tags: tags
          .split(",")
          .map((tag) => tag.trim())
          .filter(Boolean),
      });
      setContent("");
      setTitle("");
      setTags("");
      setOpen(false);
      onCreated();
    } catch (cause) {
      setError(cause as Error);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Panel
      title="Create Memory"
      actions={
        <button type="button" className="btn btn--small" onClick={() => setOpen((value) => !value)}>
          {open ? "Hide" : "New Memory"}
        </button>
      }
    >
      {!open && <EmptyState message="Click “New Memory” to create a Memory Object." />}
      {open && (
        <div>
          <div className="form-grid">
            <div className="field">
              <label htmlFor="create-title">Title</label>
              <input
                id="create-title"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="Optional title"
              />
            </div>
            <div className="field">
              <label htmlFor="create-tags">Tags</label>
              <input
                id="create-tags"
                value={tags}
                onChange={(event) => setTags(event.target.value)}
                placeholder="comma, separated, tags"
              />
            </div>
          </div>
          <div className="field">
            <label htmlFor="create-content">Content</label>
            <textarea
              id="create-content"
              value={content}
              onChange={(event) => setContent(event.target.value)}
              placeholder="Memory content…"
            />
          </div>
          {error && <ErrorBox error={error} />}
          <button
            type="button"
            className="btn btn--primary"
            disabled={submitting || !content.trim()}
            onClick={submit}
          >
            {submitting ? "Creating…" : "Create Memory"}
          </button>
        </div>
      )}
    </Panel>
  );
}

function MemoryDetailPanel({
  memory,
  onChanged,
  onDeleted,
}: {
  memory: MemoryObject;
  onChanged: (memory: MemoryObject) => void;
  onDeleted: () => void;
}) {
  const [title, setTitle] = useState(memory.title);
  const [tags, setTags] = useState(memory.tags.join(", "));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const saveMetadata = async () => {
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateMemory(memory.memory_id, {
        title,
        tags: tags
          .split(",")
          .map((tag) => tag.trim())
          .filter(Boolean),
      });
      onChanged(updated);
    } catch (cause) {
      setError(cause as Error);
    } finally {
      setSaving(false);
    }
  };

  const archive = async () => {
    try {
      onChanged(await api.archiveMemory(memory.memory_id));
    } catch (cause) {
      setError(cause as Error);
    }
  };

  const restore = async () => {
    try {
      onChanged(await api.restoreMemory(memory.memory_id));
    } catch (cause) {
      setError(cause as Error);
    }
  };

  const remove = async () => {
    if (!window.confirm("Delete this memory permanently? This cannot be undone.")) return;
    try {
      await api.deleteMemory(memory.memory_id);
      onDeleted();
    } catch (cause) {
      setError(cause as Error);
    }
  };

  return (
    <Panel title={`Memory ${memory.memory_id}`}>
      <div className="btn-row">
        <StateBadge state={memory.state} />
        <TypeBadge type={memory.type} />
        <span className="mono muted">v{memory.version}</span>
        <span className="mono muted">importance {memory.importance.toFixed(1)}</span>
      </div>
      <div className="mt-16">
        <h3 className="detail-title">{memory.title || "(untitled)"}</h3>
        <p className="muted">{memory.content}</p>
      </div>

      <div className="form-grid mt-16">
        <div className="field">
          <label htmlFor="detail-title">Title</label>
          <input
            id="detail-title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="detail-tags">Tags</label>
          <input id="detail-tags" value={tags} onChange={(event) => setTags(event.target.value)} />
        </div>
      </div>
      {error && <ErrorBox error={error} />}
      <div className="btn-row mt-8">
        <button type="button" className="btn btn--primary" disabled={saving} onClick={saveMetadata}>
          {saving ? "Saving…" : "Save Metadata"}
        </button>
        {memory.state === "active" ? (
          <button type="button" className="btn" onClick={archive}>
            Archive
          </button>
        ) : (
          <button type="button" className="btn" onClick={restore}>
            Restore
          </button>
        )}
        <button type="button" className="btn btn--danger" onClick={remove}>
          Delete
        </button>
      </div>

      <div className="mt-16">
        <h4 className="muted">Metadata</h4>
        <JsonBlock value={memory.metadata} />
      </div>
    </Panel>
  );
}
