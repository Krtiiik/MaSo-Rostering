export interface Helper {
  id: number;
  name: string;
  can_bring_notebook: boolean;
  can_bring_camera: boolean;
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

export interface AssignmentGridData {
  rooms: RoomRef[];
  roles: string[];
  role_labels: Record<string, string>;
  helpers: Helper[];
  assignments: Assignment[];
  unsatisfied_helper_ids: number[];
}

export interface DropEvent {
  helper_id: number;
  building: string;
  room: string;
  role: string;
}

// The trigger key(s) this component reports back to Python. `drop` fires
// once per completed drag-and-drop and is consumed by Streamlit after the
// resulting rerun (CCv2 triggers reset automatically — no manual dedup
// bookkeeping needed on either side).
export interface AssignmentGridState {
  [key: string]: unknown;
  drop: DropEvent;
}
