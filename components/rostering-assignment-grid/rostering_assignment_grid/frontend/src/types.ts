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

// One grid column. Normally one physical room; when adjacent rooms are
// merged via the grid's room-merge UI, `rooms` holds all of them and the
// column shows their combined content under a joined header label (see
// CLAUDE.md "Out-of-solver roles" and rostering.domain.group_adjacent_rooms).
// Merging is purely presentational — `Assignment`/`ManualEntry` below still
// always name an exact, unmerged room.
export interface RoomGroup {
  building: string;
  rooms: string[];
}

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
// cell spanning the whole table. `allowDuplicateDrop` (meaningful for
// `scope: "room"` or `scope: "building"`) marks a manual row whose cells
// also accept dropping a helper's existing chip onto the cell for the
// room/building they're already solved into — duplicating them into that
// manual role without moving their solved assignment — in addition to the
// always-available typed/picked name entry.
export interface GridRow {
  kind: "role" | "manual";
  key: string;
  label: string;
  scope?: "building" | "room" | "global";
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
  room_groups: RoomGroup[];
  rows: GridRow[];
  helpers: Helper[];
  assignments: Assignment[];
  manual_entries: ManualEntry[];
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

// Fired by clicking a column divider (merge) or a merged column's header
// (unmerge, one event listing every internal pair of that column's group).
export interface RoomMergeEvent {
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
  room_merge: RoomMergeEvent;
}
