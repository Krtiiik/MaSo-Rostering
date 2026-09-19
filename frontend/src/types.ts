export type Role = "Opravovatel" | "Menic" | "Skenovac" | "Kreslic" | "Fotograf" | "Zaloha";

export const ROLES: Role[] = ["Opravovatel", "Menic", "Skenovac", "Kreslic", "Fotograf", "Zaloha"];

export const ROLE_LABELS: Record<Role, string> = {
  Opravovatel: "Opravovatel",
  Menic: "Měnič",
  Skenovac: "Skenovač",
  Kreslic: "Kreslič",
  Fotograf: "Fotograf",
  Zaloha: "Záloha",
};

export type StructuralRole = "VedouciBudovy" | "PravaRuka" | "VedouciMistnosti" | "TechnickaPodpora";
export const STRUCTURAL_ROLES: StructuralRole[] = [
  "VedouciBudovy",
  "PravaRuka",
  "VedouciMistnosti",
  "TechnickaPodpora",
];
export const STRUCTURAL_LABELS: Record<StructuralRole, string> = {
  VedouciBudovy: "Vedoucí budovy",
  PravaRuka: "Pravá ruka",
  VedouciMistnosti: "Vedoucí místností",
  TechnickaPodpora: "Technická podpora",
};

export type OverlayRole = "Registrace" | "UvadeciPredavaniCen";
export const OVERLAY_ROLES: OverlayRole[] = ["Registrace", "UvadeciPredavaniCen"];
export const OVERLAY_LABELS: Record<OverlayRole, string> = {
  Registrace: "Registrace",
  UvadeciPredavaniCen: "Uvaděči / Předávání cen",
};

export interface Helper {
  id: number;
  name: string;
  role_preferences: Partial<Record<Role, string>>;
  building_preferences: string[];
  friends: number[];
  can_bring_notebook: boolean;
  can_bring_camera: boolean;
  unresolved_friend_names: string[];
}

export interface RoleCapacity {
  minimum: number;
  maximum: number | null;
}

export interface RoomConfig {
  name: string;
  capacities: Partial<Record<Role, RoleCapacity>>;
}

export interface BuildingConfig {
  name: string;
  rooms: RoomConfig[];
  capacities: Partial<Record<Role, RoleCapacity>>;
}

export interface Assignment {
  helper_id: number;
  helper_name: string;
  building: string;
  room: string;
  role: Role;
}

export interface StructuralAssignment {
  role: StructuralRole;
  building: string;
  room: string | null;
  helper_id: number;
}

export interface OverlayAssignment {
  role: OverlayRole;
  helper_id: number;
}

export interface ManualRoles {
  structural: StructuralAssignment[];
  overlay: OverlayAssignment[];
}

export interface SolverWeights {
  role_preference: number;
  building_mismatch: number;
  friend_unsatisfied: number;
}

export interface FriendScoringConfig {
  mode: "pairwise" | "mutual";
  symmetric: boolean;
  weight: number;
}

export interface SolverConfigT {
  weights: SolverWeights;
  friend_scoring: FriendScoringConfig;
  time_limit_seconds: number;
}

export interface Diagnostics {
  status: string | null;
  objective_value: number | null;
  unsatisfied_friend_pairs: [number, number][];
}

export interface WorkspaceState {
  helpers: Helper[];
  ingestion_warnings: string[];
  config: BuildingConfig[];
  solver_config: SolverConfigT;
  assignments: Assignment[];
  manual_roles: ManualRoles;
  diagnostics: Diagnostics;
}

export interface VersionInfo {
  slug: string;
  name: string;
  created_at: string;
}
