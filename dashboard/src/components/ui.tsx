// Small shared UI primitives for the dashboard. No third-party UI library:
// the dashboard is intentionally dependency-light (docs/Dashboard.md 2).

import type { ReactNode } from "react";

export function Panel({
  title,
  actions,
  children,
}: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="panel">
      <header className="panel-header">
        <h2>{title}</h2>
        {actions ? <div className="panel-actions">{actions}</div> : null}
      </header>
      <div className="panel-body">{children}</div>
    </section>
  );
}

export function StatCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: string | number;
  accent?: string;
}) {
  return (
    <div className={`stat-card${accent ? ` stat-card--${accent}` : ""}`}>
      <span className="stat-card-label">{label}</span>
      <span className="stat-card-value">{value}</span>
    </div>
  );
}

const STATE_COLORS: Record<string, string> = {
  active: "green",
  archived: "yellow",
  deleted: "red",
};

export function StateBadge({ state }: { state: string }) {
  return (
    <span className={`badge badge--${STATE_COLORS[state] ?? "gray"}`}>{state}</span>
  );
}

export function ResultBadge({ result }: { result: string }) {
  const tone =
    result === "SUCCESS" ? "green" : result === "DENIED" ? "yellow" : "red";
  return <span className={`badge badge--${tone}`}>{result}</span>;
}

export function TypeBadge({ type }: { type: string }) {
  return <span className="badge badge--blue">{type}</span>;
}

export function Spinner({ label }: { label: string }) {
  return (
    <div className="spinner" role="status">
      <span className="spinner-dot" aria-hidden="true" />
      {label}
    </div>
  );
}

export function ErrorBox({ error }: { error: Error }) {
  return (
    <div className="error-box" role="alert">
      <strong>{error instanceof Error && "code" in error ? (error as { code: string }).code : "ERROR"}</strong>
      <span>{error.message}</span>
    </div>
  );
}

export function EmptyState({ message }: { message: string }) {
  return <div className="empty-state">{message}</div>;
}

export function JsonBlock({ value }: { value: unknown }) {
  return <pre className="json-block">{JSON.stringify(value, null, 2)}</pre>;
}

export function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function formatScore(value: number): string {
  return value.toFixed(4);
}
