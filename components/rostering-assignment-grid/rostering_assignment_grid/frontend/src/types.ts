export interface RolePreferenceInfo {
  // 1-5, higher = more willing (see rostering.domain.Preference).
  level: number;
  // Czech wording as shown on the registration form (e.g. "Ano", "Nevadí").
  label: string;
}

export interface Helper {
  id: number;
  name: string;
  can_bring_notebook: boolean;
  can_bring_camera: boolean;
  role_preferences: Record<string, RolePreferenceInfo>;
  building_preferences: string[];
  // IDs of helpers this helper asked to share a room with.
  friends: number[];
}

export interface FriendCardEntry {
  id: number;
  name: string;
}

// Precomputed content for a helper's hover card, built once per render in
// AssignmentGrid (which has the assignment/helper lookups needed to resolve
// friend co-location) and handed to HelperChip as an opaque prop.
export interface HelperCardData {
  helper: Helper;
  roleOrder: string[];
  roleLabels: Record<string, string>;
  sharedFriends: FriendCardEntry[]; // requested friends co-located (green)
  differentFriends: FriendCardEntry[]; // requested friends elsewhere (red)
  requestedBy: FriendCardEntry[]; // helpers who requested THIS helper (purple)
}

export interface RoomRef {
  building: string;
  room: string;
}

// {row_key: {building: [[room_a, room_b], ...]}} — adjacent-room pairs
// currently merged into one wider cell for that one row only (a solved
// role's key, or a room-scoped manual role's key), like merging cells
// within a single row in Excel — every other row for the same rooms is
// unaffected (see CLAUDE.md "Out-of-solver roles" and
// rostering.domain.group_adjacent_rooms). The column layout itself (header
// rows) never merges.
export type CellMerges = Record<string, Record<string, [string, string][]>>;

export interface Assignment {
  helper_id: number;
  building: string;
  room: string;
  role: string;
}

// One row of the table. "role" rows are the drag-and-drop solver roles,
// matched against `assignments`. "manual" rows are the structural/overlay
// roles (see CLAUDE.md "Out-of-solver roles"), matched against
// `manual_entries` by key/building/room. `scope` controls how many columns
// a manual row's cells span: one per building, one per room, or a single
// cell spanning the whole table — independent of that row's own cell
// merges (see `CellMerges`), which only apply within `scope: "room"` rows.
// `allowDuplicateDrop` (meaningful for `scope: "room"` or `scope:
// "building"`) marks a manual row whose cells also accept dropping a
// helper's existing chip onto the cell for the room/building they're
// already solved into — duplicating them into that manual role without
// moving their solved assignment — in addition to the always-available
// typed/picked name entry.
export interface GridRow {
  kind: "role" | "manual";
  key: string;
  label: string;
  scope?: "building" | "room" | "global";
  // "manual" rows filled by people who typically never registered as a
  // helper (e.g. Vedoucí budovy) render as plain free text instead of an
  // autocomplete against registered helper names.
  plain_text?: boolean;
  // "manual" rows for a single-holder role (e.g. one building lead) cap
  // their cell at one name instead of allowing a list.
  single_entry?: boolean;
  // Whether helpers can express a preference for this role on the form —
  // false for Záloha, which is a solver-only overflow role never offered as
  // a choice (see CLAUDE.md). Omitted/true for every other role row.
  preferenceable?: boolean;
  allowDuplicateDrop?: boolean;
}

export interface ManualEntry {
  key: string;
  building: string | null;
  room: string | null;
  helper_id: number | null;
  name: string;
}

export interface AssignmentGridData {
  rooms: RoomRef[];
  rows: GridRow[];
  helpers: Helper[];
  assignments: Assignment[];
  manual_entries: ManualEntry[];
  cell_merges: CellMerges;
  helper_names: string[];
}

export interface DropEvent {
  helper_id: number;
  building: string;
  room: string;
  role: string;
}

// Fired whenever a manual-role cell's list of names changes; `names` is the
// cell's full new list (not a single added/removed entry).
export interface ManualSetEvent {
  key: string;
  building: string | null;
  room: string | null;
  names: string[];
}

// Fired by clicking the edge between two of one row's cells (merge) or an
// already-merged cell in that row (unmerge, listing every internal pair of
// that cell's group). `key` is the row it applies to — a merge in one row
// never affects any other row for the same rooms.
export interface CellMergeEvent {
  key: string;
  building: string;
  pairs: [string, string][];
  merged: boolean;
}

// The trigger key(s) this component reports back to Python. All three fire
// once per completed edit and are consumed by Streamlit after the
// resulting rerun (CCv2 triggers reset automatically — no manual dedup
// bookkeeping needed on either side).
export interface AssignmentGridState {
  [key: string]: unknown;
  drop: DropEvent;
  manual_set: ManualSetEvent;
  cell_merge: CellMergeEvent;
}
