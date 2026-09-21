export interface Helper {
  id: number;
  name: string;
  can_bring_notebook: boolean;
  can_bring_camera: boolean;
  friends: number[];
}

export interface RoomRef {
  building: string;
  room: string;
}

export interface Assignment {
  helper_id: number;
  building: string;
  room: string;
  role: string;
}

// One row of the table. "role" rows are the drag-and-drop solver roles,
// matched against `assignments`. "manual" rows are the non-droppable
// structural/overlay roles (see CLAUDE.md "Out-of-solver roles"), matched
// against `manual_entries` by key/building/room. `scope` controls how many
// columns a manual row's cells span: one per building, one per room, or a
// single cell spanning the whole table.
export interface GridRow {
  kind: "role" | "manual";
  key: string;
  label: string;
  scope?: "building" | "room" | "global";
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

// The trigger key(s) this component reports back to Python. Both `drop` and
// `manual_set` fire once per completed edit and are consumed by Streamlit
// after the resulting rerun (CCv2 triggers reset automatically — no manual
// dedup bookkeeping needed on either side).
export interface AssignmentGridState {
  [key: string]: unknown;
  drop: DropEvent;
  manual_set: ManualSetEvent;
}
