import { useEffect, useState } from "react";
import { api } from "../api";
import type { VersionInfo, WorkspaceState } from "../types";

interface Props {
  onStateChange: (state: WorkspaceState) => void;
}

export function VersionsPanel({ onStateChange }: Props) {
  const [versions, setVersions] = useState<VersionInfo[]>([]);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    api.listVersions().then(setVersions).catch((e) => setError(String(e)));
  }

  useEffect(refresh, []);

  async function save() {
    if (!name.trim()) return;
    try {
      await api.createVersion(name.trim());
      setName("");
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function restore(slug: string) {
    try {
      onStateChange(await api.restoreVersion(slug));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function remove(slug: string) {
    try {
      await api.deleteVersion(slug);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="versions-panel">
      <h3>Versions</h3>
      <div className="actions">
        <input
          value={name}
          placeholder="Version name…"
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && save()}
        />
        <button onClick={save}>Save current as version</button>
      </div>
      {error && <p className="error">{error}</p>}
      <ul className="version-list">
        {versions.map((v) => (
          <li key={v.slug}>
            <span>{v.name}</span>
            <span className="muted">{new Date(v.created_at).toLocaleString()}</span>
            <button onClick={() => restore(v.slug)}>Restore</button>
            <button onClick={() => remove(v.slug)}>Delete</button>
          </li>
        ))}
        {versions.length === 0 && <li className="muted">No saved versions yet.</li>}
      </ul>
    </div>
  );
}
