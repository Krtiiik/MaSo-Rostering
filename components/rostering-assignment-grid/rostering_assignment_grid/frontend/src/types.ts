export interface RolePreferenceInfo {
  // 1-5, higher = more willing (see rostering.domain.Preference).
  level: number;
  // Czech wording as shown on the registration form (e.g. "Ano", "Nevadí").
  label: string;
}

// One Tag pill (see CONTEXT.md "Tag"), computed live on the Python side.
export interface TagPill {
  name: string;
  colour: string; // "#rrggbb"
}

// A Helper's Tags: the ones assigned directly (solid pills) and the ones only
// implied through a direct Tag's ancestors (dashed pills).
export interface HelperTags {
  direct: TagPill[];
  implied: TagPill[];
}

export interface Helper {
  id: number;
  name: string;
  // Absent when the Season has no Tags.
  tags?: HelperTags;
  can_bring_notebook: boolean;
  can_bring_camera: boolean;
  role_preferences: Record<string, RolePreferenceInfo>;
  building_preferences: string[];
  // IDs of helpers this helper asked to share a room with.
  friends: number[];
  // The answers (e.g. "Building preference") a re-submitted survey row changed
  // since this Helper was placed; absent or empty when nothing changed.
  answers_changed?: string[];
  // The Forced friends groups in force that bind this Helper, worded for the
  // tooltip ("Rodina (same Building, Room)"); absent or empty when none does.
  forced_groups?: string[];
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
  // A Locked Assignment (see CONTEXT.md): a full Solve keeps it. Absent
  // means unlocked.
  locked?: boolean;
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
  // "manual" rows for the leadership slots, which take a tracked Organizer:
  // their input autocompletes against `organizer_names` instead of helpers.
  organizer?: boolean;
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
  // Set on a leadership-slot entry held by a tracked Organizer.
  organizer_id?: number | null;
  // A leadership-slot entry saved before Organizers existed (a Helper or
  // hand-typed text): still shown, marked as not yet a tracked Organizer,
  // until it is replaced by picking one.
  legacy?: boolean;
  // An Organizer's Tag pills (shown under "Show tags"), whether the Tag filter
  // dims them, and the Broken-rule lines their placement is part of — the same
  // things a Helper's chip carries.
  tags?: HelperTags | null;
  dimmed?: boolean;
  broken?: string[];
}

// A light "this breaks a rule" mark (see CONTEXT.md "Broken rule"), computed
// live on the Python side and only displayed here. `role: null` marks the
// whole Room (its column header) instead of one role's cell; `line` is the
// banner's wording, shown as a tooltip.
export interface BrokenCellMark {
  building: string;
  room: string;
  role: string | null;
  line: string;
}

export interface BrokenChipMark {
  helper_id: number;
  line: string;
}

export interface BrokenOrganizerMark {
  organizer_id: number;
  line: string;
}

export interface BrokenMarks {
  cells: BrokenCellMark[];
  helpers: BrokenChipMark[];
  // Organizers' slot chips; each is also reported on its ManualEntry.
  organizers?: BrokenOrganizerMark[];
}

export interface AssignmentGridData {
  rooms: RoomRef[];
  rows: GridRow[];
  helpers: Helper[];
  assignments: Assignment[];
  manual_entries: ManualEntry[];
  cell_merges: CellMerges;
  helper_names: string[];
  organizer_names?: string[];
  broken_marks?: BrokenMarks;
  // Render each Helper's Tag pills under their name (hidden by default).
  show_tags?: boolean;
  // Helpers the Tag filter dims (never hides): they stay in place and
  // draggable, just faded.
  dimmed_helper_ids?: number[];
}

export interface DropEvent {
  helper_id: number;
  building: string;
  room: string;
  role: string;
}

// Fired by ctrl/cmd-clicking a placed chip or pressing the hover card's
// Lock/Unlock button; `locked` is the lock's new value.
export interface LockEvent {
  helper_id: number;
  locked: boolean;
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

// The trigger key(s) this component reports back to Python. All four fire
// once per completed edit and are consumed by Streamlit after the
// resulting rerun (CCv2 triggers reset automatically — no manual dedup
// bookkeeping needed on either side).
export interface AssignmentGridState {
  [key: string]: unknown;
  drop: DropEvent;
  manual_set: ManualSetEvent;
  cell_merge: CellMergeEvent;
  lock: LockEvent;
}
