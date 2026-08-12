import { useState } from "react";
import { ConfigurationModule } from "./modules/ConfigurationModule";
import { GraphModule } from "./modules/GraphModule";
import { LogsModule } from "./modules/LogsModule";
import { MemoryExplorerModule } from "./modules/MemoryExplorerModule";
import { RelationshipsModule } from "./modules/RelationshipsModule";
import { SearchModule } from "./modules/SearchModule";
import { StatisticsModule } from "./modules/StatisticsModule";
import { VersionsModule } from "./modules/VersionsModule";

export type ModuleKey =
  | "statistics"
  | "memories"
  | "search"
  | "graph"
  | "relationships"
  | "versions"
  | "configuration"
  | "logs";

const MODULES: { key: ModuleKey; label: string }[] = [
  { key: "statistics", label: "Statistics" },
  { key: "memories", label: "Memory Explorer" },
  { key: "search", label: "Search" },
  { key: "graph", label: "Graph Viewer" },
  { key: "relationships", label: "Relationship Viewer" },
  { key: "versions", label: "Version History" },
  { key: "configuration", label: "Configuration" },
  { key: "logs", label: "Logs" },
];

export default function App() {
  const [activeModule, setActiveModule] = useState<ModuleKey>("statistics");

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">🧠</span>
          <div>
            <h1>MemOS</h1>
            <p>Dashboard</p>
          </div>
        </div>
        <nav className="nav" aria-label="Dashboard modules">
          {MODULES.map((module) => (
            <button
              key={module.key}
              type="button"
              className={`nav-item${activeModule === module.key ? " nav-item--active" : ""}`}
              onClick={() => setActiveModule(module.key)}
            >
              {module.label}
            </button>
          ))}
        </nav>
      </aside>
      <main className="content">
        {activeModule === "statistics" && <StatisticsModule />}
        {activeModule === "memories" && <MemoryExplorerModule />}
        {activeModule === "search" && <SearchModule />}
        {activeModule === "graph" && <GraphModule />}
        {activeModule === "relationships" && <RelationshipsModule />}
        {activeModule === "versions" && <VersionsModule />}
        {activeModule === "configuration" && <ConfigurationModule />}
        {activeModule === "logs" && <LogsModule />}
      </main>
    </div>
  );
}
