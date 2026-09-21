import { useState } from "react";
import type { ManualEntry } from "./types";

interface Props {
  entries: ManualEntry[];
  colSpan: number;
  datalistId: string;
  onChange: (names: string[]) => void;
}

/**
 * A non-droppable cell for a manual structural/overlay role. Holds zero or
 * more names, each either a registered helper (picked from `datalistId`'s
 * suggestions) or a hand-typed name for someone unregistered — manual roles
 * are commonly filled by people who never registered as a helper.
 */
export function ManualCell({ entries, colSpan, datalistId, onChange }: Props) {
  const [draft, setDraft] = useState("");
  const names = entries.map((e) => e.name);

  function commitDraft() {
    const value = draft.trim();
    if (value && !names.includes(value)) {
      onChange([...names, value]);
    }
    setDraft("");
  }

  function removeName(name: string) {
    onChange(names.filter((n) => n !== name));
  }

  return (
    <td className="grid-cell manual-cell" colSpan={colSpan}>
      <div className="grid-cell-inner">
        {entries.map((entry) => (
          <span key={entry.name} className={`manual-chip${entry.helper_id === null ? " manual-chip-new" : ""}`}>
            {entry.name}
            <button
              type="button"
              className="manual-chip-remove"
              aria-label={`Remove ${entry.name}`}
              onClick={() => removeName(entry.name)}
            >
              ×
            </button>
          </span>
        ))}
        <input
          className="manual-cell-input"
          list={datalistId}
          value={draft}
          placeholder="+ add name"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              commitDraft();
            }
          }}
          onBlur={commitDraft}
        />
      </div>
    </td>
  );
}
