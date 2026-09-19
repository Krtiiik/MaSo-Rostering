import { useState } from "react";
import { api } from "../api";
import type { WorkspaceState } from "../types";

interface Props {
  state: WorkspaceState;
  onStateChange: (state: WorkspaceState) => void;
}

export function UploadPage({ state, onStateChange }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFile(file: File) {
    setBusy(true);
    setError(null);
    try {
      const next = await api.upload(file);
      onStateChange(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <h2>1. Upload responses</h2>
      <p>
        Upload the raw Google Forms export (.xlsx) for the current helper responses. This replaces
        any previously uploaded helpers.
      </p>
      <input
        type="file"
        accept=".xlsx"
        disabled={busy}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) handleFile(file);
        }}
      />
      {busy && <p>Uploading and parsing…</p>}
      {error && <p className="error">{error}</p>}

      {state.helpers.length > 0 && (
        <div className="card">
          <p>
            <strong>{state.helpers.length}</strong> helpers loaded.
          </p>
          {state.ingestion_warnings.length > 0 && (
            <details>
              <summary>{state.ingestion_warnings.length} ingestion warning(s)</summary>
              <ul className="warnings">
                {state.ingestion_warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
