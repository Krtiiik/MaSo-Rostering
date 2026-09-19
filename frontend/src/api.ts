import type { BuildingConfig, ManualRoles, Role, SolverConfigT, VersionInfo, WorkspaceState } from "./types";

const BASE = "/api";

async function asJson<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}));
    throw new Error(detail.detail || resp.statusText);
  }
  return resp.json() as Promise<T>;
}

function putJson<T>(path: string, body: unknown): Promise<T> {
  return fetch(`${BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(asJson<T>);
}

export const api = {
  getState: (): Promise<WorkspaceState> => fetch(`${BASE}/state`).then((r) => asJson<WorkspaceState>(r)),

  reset: (): Promise<WorkspaceState> =>
    fetch(`${BASE}/reset`, { method: "POST" }).then((r) => asJson<WorkspaceState>(r)),

  upload: (file: File): Promise<WorkspaceState> => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${BASE}/upload`, { method: "POST", body: form }).then((r) => asJson<WorkspaceState>(r));
  },

  resolveFriend: (
    helperId: number,
    body: { name: string; action: "resolve" | "dismiss"; resolved_helper_id?: number },
  ): Promise<WorkspaceState> => putJson(`/helpers/${helperId}/friends`, body),

  putConfig: (buildings: BuildingConfig[]): Promise<WorkspaceState> => putJson("/config", buildings),

  putSolverConfig: (config: SolverConfigT): Promise<WorkspaceState> => putJson("/solver-config", config),

  solve: (): Promise<WorkspaceState> =>
    fetch(`${BASE}/solve`, { method: "POST" }).then((r) => asJson<WorkspaceState>(r)),

  moveHelper: (helperId: number, building: string, room: string, role: Role): Promise<WorkspaceState> =>
    putJson(`/assignments/${helperId}`, { building, room, role }),

  putManualRoles: (manual: ManualRoles): Promise<WorkspaceState> => putJson("/manual-roles", manual),

  listVersions: (): Promise<VersionInfo[]> => fetch(`${BASE}/versions`).then((r) => asJson<VersionInfo[]>(r)),

  createVersion: (name: string): Promise<VersionInfo> =>
    fetch(`${BASE}/versions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }).then((r) => asJson<VersionInfo>(r)),

  restoreVersion: (slug: string): Promise<WorkspaceState> =>
    fetch(`${BASE}/versions/${slug}/restore`, { method: "POST" }).then((r) => asJson<WorkspaceState>(r)),

  deleteVersion: (slug: string): Promise<{ deleted: string }> =>
    fetch(`${BASE}/versions/${slug}`, { method: "DELETE" }).then((r) => asJson<{ deleted: string }>(r)),

  exportUrl: (): string => `${BASE}/export.xlsx`,
};
