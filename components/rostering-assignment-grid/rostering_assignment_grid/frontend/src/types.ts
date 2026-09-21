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
  unsatisfied_friend_pairs: [number, number][];
  satisfied_friend_pairs: [number, number][];
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
