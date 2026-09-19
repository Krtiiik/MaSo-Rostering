import { useMemo, useState } from "react";
import { api } from "../api";
import type { Helper, WorkspaceState } from "../types";
import { ROLES, ROLE_LABELS } from "../types";

interface Props {
  state: WorkspaceState;
  onStateChange: (state: WorkspaceState) => void;
  onContinue: () => void;
}

const PREF_ROLES = ROLES.filter((role) => role !== "Zaloha");

export function UploadPage({ state, onStateChange, onContinue }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);

  const helpersById = useMemo(() => {
    const map = new Map<number, Helper>();
    for (const h of state.helpers) map.set(h.id, h);
    return map;
  }, [state.helpers]);

  const unresolvedCount = state.helpers.reduce((sum, h) => sum + h.unresolved_friend_names.length, 0);

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

  async function handleResolve(helperId: number, name: string, resolvedHelperId: number) {
    const key = `${helperId}:${name}`;
    setPendingKey(key);
    setError(null);
    try {
      const next = await api.resolveFriend(helperId, { name, action: "resolve", resolved_helper_id: resolvedHelperId });
      onStateChange(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPendingKey(null);
    }
  }

  async function handleDismiss(helperId: number, name: string) {
    const key = `${helperId}:${name}`;
    setPendingKey(key);
    setError(null);
    try {
      const next = await api.resolveFriend(helperId, { name, action: "dismiss" });
      onStateChange(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPendingKey(null);
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
            {unresolvedCount > 0 && (
              <>
                {" "}
                <strong>{unresolvedCount}</strong> friend name{unresolvedCount === 1 ? "" : "s"} still need
                matching in the table below.
              </>
            )}
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
          <button className="cta-button" onClick={onContinue}>
            Continue to buildings &amp; rooms →
          </button>
        </div>
      )}

      {state.helpers.length > 0 && (
        <div className="grid-scroll">
          <table className="helpers-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Buildings</th>
                <th>Equipment</th>
                <th>Role preferences</th>
                <th>Friends</th>
              </tr>
            </thead>
            <tbody>
              {state.helpers.map((h) => (
                <tr key={h.id}>
                  <td>{h.name}</td>
                  <td>
                    {h.building_preferences.length > 0 ? (
                      h.building_preferences.join(", ")
                    ) : (
                      <span className="muted">any</span>
                    )}
                  </td>
                  <td>
                    {h.can_bring_notebook && <span title="Can bring a notebook">💻</span>}{" "}
                    {h.can_bring_camera && <span title="Can bring a camera">📷</span>}
                    {!h.can_bring_notebook && !h.can_bring_camera && <span className="muted">—</span>}
                  </td>
                  <td>
                    <div className="role-pref-list">
                      {PREF_ROLES.map((role) => {
                        const pref = h.role_preferences[role];
                        if (!pref) return null;
                        return (
                          <span
                            key={role}
                            className="role-pref-badge"
                            title={`${ROLE_LABELS[role]}: ${pref}`}
                          >
                            {ROLE_LABELS[role].slice(0, 3)}: {pref}
                          </span>
                        );
                      })}
                    </div>
                  </td>
                  <td>
                    <div className="friend-list">
                      {h.friends.map((fid) => (
                        <span key={fid} className="friend-chip resolved">
                          {helpersById.get(fid)?.name ?? `#${fid}`}
                        </span>
                      ))}
                      {h.unresolved_friend_names.map((name) => {
                        const key = `${h.id}:${name}`;
                        const isPending = pendingKey === key;
                        return (
                          <span key={name} className="friend-chip unresolved">
                            <span className="unresolved-name">{name}</span>
                            <select
                              disabled={isPending}
                              defaultValue=""
                              onChange={(e) => {
                                const value = e.target.value;
                                if (value) handleResolve(h.id, name, Number(value));
                              }}
                            >
                              <option value="" disabled>
                                Match to…
                              </option>
                              {state.helpers
                                .filter((candidate) => candidate.id !== h.id)
                                .map((candidate) => (
                                  <option key={candidate.id} value={candidate.id}>
                                    {candidate.name}
                                  </option>
                                ))}
                            </select>
                            <button type="button" disabled={isPending} onClick={() => handleDismiss(h.id, name)}>
                              Not attending
                            </button>
                          </span>
                        );
                      })}
                      {h.friends.length === 0 && h.unresolved_friend_names.length === 0 && (
                        <span className="muted">—</span>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
