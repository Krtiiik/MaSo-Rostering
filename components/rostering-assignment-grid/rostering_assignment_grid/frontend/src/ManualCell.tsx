import { useDndContext, useDroppable } from "@dnd-kit/core";
import { useId, useState } from "react";
import type { MouseEvent } from "react";
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
  // only while the dragged helper's own solved-role location matches
  // `building` (and, if `rooms` is non-null, one of `rooms` too — a null
  // `rooms` means this is a building-scoped cell, matched on building
  // alone; a `rooms` array with more than one entry means the underlying
  // room columns are currently merged, see CLAUDE.md "Out-of-solver
  // roles"). `dropId` must be unique across the grid.
  dropId?: string;
  manualKey?: string;
  building?: string | null;
  rooms?: string[] | null;
  helperLocations?: Map<number, HelperLocation>;
  // Present only when this cell has a mergeable neighbor to its right in
  // this specific row (see CLAUDE.md "Out-of-solver roles") — renders a
  // small clickable edge handle.
  onMergeRight?: () => void;
  // Present only when this cell is currently merged (spans more than one
  // room) — renders a small clickable "unmerge" icon.
  onUnmerge?: () => void;
}

/**
 * A cell for a manual structural/overlay role. Holds zero or more names,
 * each either a registered helper (picked from `datalistId`'s suggestions
 * or, if `dropId` is set, dragged in) or a hand-typed name for someone
 * unregistered — manual roles are commonly filled by people who never
 * registered as a helper. A dragged-in registered helper's chip is styled
 * with a dotted border to mark it as a duplicate of their solved-role
 * placement, not a move. Building-scoped duplicate-drop cells (`rooms` left
 * null) accept a drop from anywhere in that building; room-scoped ones
 * (`rooms` set) require the dragged helper's own room to be one of `rooms`.
 */
export function ManualCell({
  entries,
  colSpan,
  datalistId,
  onChange,
  dropId,
  manualKey,
  building,
  rooms,
  helperLocations,
  onMergeRight,
  onUnmerge,
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
  let locationMismatch = false;
  if (droppable && active) {
    const loc = helperLocations?.get(Number(active.id));
    const matches = !!loc && loc.building === building && (rooms == null || rooms.includes(loc.room));
    if (matches) {
      dropDisabled = false;
    } else {
      locationMismatch = true;
    }
  }

  const { setNodeRef, isOver } = useDroppable({
    id: dropId ?? fallbackId,
    disabled: !droppable || dropDisabled,
    data: droppable ? { type: "duplicate", key: manualKey, building, rooms: rooms ?? null } : undefined,
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

  function stop<T>(handler: () => T) {
    return (e: MouseEvent) => {
      e.stopPropagation();
      handler();
    };
  }

  const cellClass = [
    "grid-cell",
    "manual-cell",
    isOver && !dropDisabled ? "drop-over" : "",
    droppable && locationMismatch ? "drop-disabled" : "",
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
      {onMergeRight && (
        <div className="cell-merge-handle" title="Click to merge with the next cell" onClick={stop(onMergeRight)} />
      )}
      {onUnmerge && (
        <button
          type="button"
          className="cell-unmerge-handle"
          title="Click to split this merged cell back apart"
          onClick={stop(onUnmerge)}
        >
          ⊟
        </button>
      )}
    </td>
  );
}
