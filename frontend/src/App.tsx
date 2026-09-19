import { useEffect, useState } from "react";
import { api } from "./api";
import { ConfigPage } from "./components/ConfigPage";
import { GridPage } from "./components/GridPage";
import { UploadPage } from "./components/UploadPage";
import { VersionsPanel } from "./components/VersionsPanel";
import type { WorkspaceState } from "./types";

type Tab = "upload" | "config" | "grid";

export default function App() {
  const [state, setState] = useState<WorkspaceState | null>(null);
  const [tab, setTab] = useState<Tab>("upload");

  useEffect(() => {
    api.getState().then(setState);
  }, []);

  function onStateChange(next: WorkspaceState) {
    setState(next);
  }

  async function resetAll() {
    if (!confirm("Start over? This clears the current workspace (saved versions are kept).")) return;
    setState(await api.reset());
    setTab("upload");
  }

  if (!state) return <div className="page">Loading…</div>;

  return (
    <div className="app">
      <header className="app-header">
        <h1>Rostering</h1>
        <nav>
          <button className={tab === "upload" ? "active" : ""} onClick={() => setTab("upload")}>
            1. Upload
          </button>
          <button className={tab === "config" ? "active" : ""} onClick={() => setTab("config")}>
            2. Buildings
          </button>
          <button className={tab === "grid" ? "active" : ""} onClick={() => setTab("grid")}>
            3. Roster
          </button>
        </nav>
        <button className="reset-button" onClick={resetAll}>
          Start over
        </button>
      </header>

      <div className="app-body">
        <main className="app-main">
          {tab === "upload" && (
            <UploadPage state={state} onStateChange={onStateChange} onContinue={() => setTab("config")} />
          )}
          {tab === "config" && (
            <ConfigPage state={state} onStateChange={onStateChange} onSolved={() => setTab("grid")} />
          )}
          {tab === "grid" && <GridPage state={state} onStateChange={onStateChange} />}
        </main>
        <aside className="app-sidebar">
          <VersionsPanel onStateChange={onStateChange} />
        </aside>
      </div>
    </div>
  );
}
