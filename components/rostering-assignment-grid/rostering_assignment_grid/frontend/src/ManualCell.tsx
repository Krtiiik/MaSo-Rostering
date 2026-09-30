import { useDndContext } from "@dnd-kit/core";
import { useId, useRef, useState } from "react";
import { Cell } from "./Cell";
import { OrganizerChip } from "./OrganizerChip";
import type { ManualEntry } from "./types";
import { tagStripeStyle, tagTitle } from "./tagStripes";

interface HelperLocation {
  building: string;
  room: string;
}

interface Props {
  entries: ManualEntry[];
  colSpan: number;
  // Omitted for roles rendered as plain free text (see GridRow.plain_text) —
  // no autocomplete suggestions against registered helper names.
  datalistId?: string;
  // Single-holder role (see GridRow.single_entry) — cap the cell at one
  // name; the add-input is hidden once a name is set, so replacing it
  // requires removing the existing one first.
  singleEntry?: boolean;
  // The Tags overlay is on: stripe an Organizer's chip in their direct Tag colours.
  showTags?: boolean;
  onChange: (names: string[]) => void;
  // When set, this cell also accepts dropping a helper's existing chip —
  // only while the dragged helper's own solved-role location matches
  // `building` (and, if `rooms` is non-null, one of `rooms` too — a null
  // `rooms` means this is a building-scoped cell, matched on building
  // alone; a `rooms` array with more than one entry means the underlying
  // room columns are currently merged, see CLAUDE.md "Out-of-solver
  // roles"). `dropId` must be unique across the grid.
  dropId?: string;
  // The row's key; the slot an Organizer's chip is dragged out of is named by it.
  manualKey?: string;
  // An Organizer row's cell (a leadership slot): it takes Organizers' chips, and
  // nobody else's, where the other droppable cells take Helpers' (see `dropId`).
  organizerSlot?: boolean;
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
 * A cell for a manual structural/overlay role — the same table cell as a solver
 * role's (`Cell`: same droppable, same merge handles, chips in the same column),
 * told apart only by the "Manuální role" note on its row label. It holds zero
 * or more names, each either a registered helper (picked from `datalistId`'s
 * suggestions, when provided, or, if `dropId` is set, dragged in) or a
 * hand-typed name for someone unregistered — manual roles are commonly filled by people who
 * never registered as a helper. A single-holder role (see
 * GridRow.single_entry) caps the cell at one name, no longer accepting a click
 * to add once one is set. A name is added by clicking the cell, which opens a
 * name field (Enter or leaving the field saves it, Escape cancels). A
 * dragged-in registered helper's chip is styled with a dotted border to mark
 * it as a duplicate of their solved-role placement, not a move. Building-scoped duplicate-drop cells (`rooms` left null)
 * accept a drop from anywhere in that building; room-scoped ones (`rooms`
 * set) require the dragged helper's own room to be one of `rooms` (more
 * than one when the underlying room columns are currently merged).
 */
export function ManualCell({
  entries,
  colSpan,
  datalistId,
  singleEntry = false,
  showTags = false,
  onChange,
  dropId,
  manualKey,
  organizerSlot = false,
  building,
  rooms,
  helperLocations,
  onMergeRight,
  onUnmerge,
}: Props) {
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  // Set by Escape so the blur that follows the field closing does not save it.
  const cancelled = useRef(false);
  const names = entries.map((e) => e.name);
  const canAddMore = !singleEntry || entries.length === 0;
  const droppable = dropId !== undefined;
  const { active } = useDndContext();
  // Every ManualCell registers a droppable (even non-droppable ones, always
  // disabled) so each needs its own unique id — dnd-kit's droppable
  // registry is keyed by id regardless of `disabled`.
  const fallbackId = useId();

  // A drop is refused unless the dragged chip is of the kind the cell takes (see
  // Cell.accepts) and, for a Helper's chip, the cell is for the Building/Room they
  // are placed in.
  let dropDisabled = true;
  let locationMismatch = false;
  if (droppable && active) {
    const dragKind = active.data.current?.kind;
    if (organizerSlot) {
      dropDisabled = dragKind !== "organizer";
    } else if (dragKind === "helper") {
      const loc = helperLocations?.get(Number(active.id));
      const matches = !!loc && loc.building === building && (rooms == null || rooms.includes(loc.room));
      dropDisabled = !matches;
      locationMismatch = !matches;
    }
  }

  // Saves the typed name and, for a single-holder cell (now full) or when
  // `keepOpen` is false, closes the field; a multi-name cell stays open after
  // Enter so several names can follow one another.
  function commitDraft(keepOpen: boolean) {
    if (cancelled.current) {
      cancelled.current = false;
      return;
    }
    const value = draft.trim();
    if (value && !names.includes(value)) {
      onChange([...names, value]);
    }
    setDraft("");
    if (!keepOpen || singleEntry) setEditing(false);
  }

  function removeName(name: string) {
    onChange(names.filter((n) => n !== name));
  }

  // A click on a chip (stopped below) is not a click on the cell, which opens
  // the name field.
  return (
    <Cell
      id={dropId ?? fallbackId}
      colSpan={colSpan}
      disabled={!droppable || dropDisabled}
      accepts={organizerSlot ? "organizer" : "helper"}
      dropData={
        !droppable
          ? undefined
          : organizerSlot
            ? { type: "organizer_slot", key: manualKey, building, room: rooms?.[0] ?? null }
            : { type: "duplicate", key: manualKey, building, rooms: rooms ?? null }
      }
      className={`manual-cell${canAddMore ? " manual-cell-editable" : ""}${droppable && locationMismatch ? " drop-disabled" : ""}`}
      title={canAddMore ? "Kliknutím přidáte jméno" : undefined}
      onClick={canAddMore ? () => setEditing(true) : undefined}
      onMergeRight={onMergeRight}
      onUnmerge={onUnmerge}
    >
      {entries.map((entry) =>
        entry.organizer_id != null ? (
          <OrganizerChip
            key={entry.name}
            organizerId={entry.organizer_id}
            name={entry.name}
            source={{ key: entry.key, building: entry.building ?? building ?? "", room: entry.room }}
            showTags={showTags}
            tags={entry.tags}
            dimmed={entry.dimmed}
            broken={entry.broken}
            onRemove={() => removeName(entry.name)}
          />
        ) : (
        <span
          key={entry.name}
          title={[...(entry.broken ?? []), ...(showTags ? [tagTitle(entry.tags) ?? ""] : [])].filter(Boolean).join("\n") || undefined}
          style={showTags ? tagStripeStyle(entry.tags) : undefined}
          className={`manual-chip${showTags && tagStripeStyle(entry.tags) ? " tag-striped" : ""}${entry.dimmed ? " dimmed" : ""}${entry.broken?.length ? " broken" : ""}${
            entry.legacy || entry.helper_id === null
              ? " manual-chip-new"
              : droppable
                ? " manual-chip-duplicate"
                : ""
          }`}
          onClick={(e) => e.stopPropagation()}
        >
          {entry.name}
          {entry.legacy && (
            <span className="manual-chip-badge" title="Zatím to není evidovaný organizátor — odeberte ho a vyberte nebo přidejte organizátora, který ho nahradí">
              neevidován
            </span>
          )}
          <button
            type="button"
            className="manual-chip-remove"
            aria-label={`Odebrat ${entry.name}`}
            onClick={() => removeName(entry.name)}
          >
            ×
          </button>
        </span>
        ),
      )}
      {canAddMore && editing && (
        <input
          className="manual-cell-input"
          list={datalistId}
          value={draft}
          autoFocus
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              commitDraft(true);
            } else if (e.key === "Escape") {
              cancelled.current = true;
              setDraft("");
              setEditing(false);
            }
          }}
          onBlur={() => commitDraft(false)}
        />
      )}
    </Cell>
  );
}
