import { useDndContext, useDroppable } from "@dnd-kit/core";
import { useId, useState } from "react";
import type { ManualEntry } from "./types";

interface HelperLocation {
  building: string;
  room: string;
}

interface Props {
  entries: ManualEntry[];
  colSpan: number;
  datalistId: string;
  onChange: (names: string[]) => void;
  // When set, this cell also accepts dropping a helper's existing chip —
  // only while the dragged helper's own solved-role room matches
  // `building`/`room` (see CLAUDE.md "Out-of-solver roles"); `dropId` must
  // be unique across the grid.
  dropId?: string;
  manualKey?: string;
  building?: string | null;
  room?: string | null;
  helperLocations?: Map<number, HelperLocation>;
}

/**
 * A cell for a manual structural/overlay role. Holds zero or more names,
 * each either a registered helper (picked from `datalistId`'s suggestions
 * or, if `dropId` is set, dragged in) or a hand-typed name for someone
 * unregistered — manual roles are commonly filled by people who never
 * registered as a helper. A dragged-in registered helper's chip is styled
 * with a dotted border to mark it as a duplicate of their solved-role
 * placement, not a move.
 */
export function ManualCell({
  entries,
  colSpan,
  datalistId,
  onChange,
  dropId,
  manualKey,
  building,
  room,
  helperLocations,
}: Props) {
  const [draft, setDraft] = useState("");
  const names = entries.map((e) => e.name);
  const droppable = dropId !== undefined;
  const { active } = useDndContext();
  // Every ManualCell registers a droppable (even non-droppable ones, always
  // disabled) so each needs its own unique id — dnd-kit's droppable
  // registry is keyed by id regardless of `disabled`.
  const fallbackId = useId();

  let dropDisabled = true;
  let roomMismatch = false;
  if (droppable && active) {
    const loc = helperLocations?.get(Number(active.id));
    if (loc && loc.building === building && loc.room === room) {
      dropDisabled = false;
    } else {
      roomMismatch = true;
    }
  }

  const { setNodeRef, isOver } = useDroppable({
    id: dropId ?? fallbackId,
    disabled: !droppable || dropDisabled,
    data: droppable ? { type: "duplicate", key: manualKey, building, room } : undefined,
  });

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

  const cellClass = [
    "grid-cell",
    "manual-cell",
    isOver && !dropDisabled ? "drop-over" : "",
    droppable && roomMismatch ? "drop-disabled" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <td ref={droppable ? setNodeRef : undefined} className={cellClass} colSpan={colSpan}>
      <div className="grid-cell-inner">
        {entries.map((entry) => (
          <span
            key={entry.name}
            className={`manual-chip${
              entry.helper_id === null ? " manual-chip-new" : droppable ? " manual-chip-duplicate" : ""
            }`}
          >
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
