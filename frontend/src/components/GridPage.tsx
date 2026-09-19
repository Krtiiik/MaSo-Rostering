import { useMemo, useState } from "react";
import { DndContext } from "@dnd-kit/core";
import type { DragEndEvent } from "@dnd-kit/core";
import { api } from "../api";
import { Cell } from "./Cell";
import { HelperChip } from "./HelperChip";
import {
  OVERLAY_LABELS,
  OVERLAY_ROLES,
  ROLES,
  ROLE_LABELS,
  STRUCTURAL_LABELS,
  STRUCTURAL_ROLES,
} from "../types";
import type {
  Helper,
  ManualRoles,
  OverlayRole,
  Role,
  StructuralAssignment,
  StructuralRole,
  WorkspaceState,
} from "../types";

interface Props {
  state: WorkspaceState;
  onStateChange: (state: WorkspaceState) => void;
}

export function GridPage({ state, onStateChange }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const helpersById = useMemo(() => {
    const map = new Map<number, Helper>();
    for (const h of state.helpers) map.set(h.id, h);
    return map;
  }, [state.helpers]);

  const assignmentByHelper = useMemo(() => {
    const map = new Map<number, (typeof state.assignments)[number]>();
    for (const a of state.assignments) map.set(a.helper_id, a);
    return map;
  }, [state.assignments]);

  const unassignedHelpers = state.helpers.filter((h) => !assignmentByHelper.has(h.id));

  const unsatisfiedHelperIds = useMemo(() => {
    const set = new Set<number>();
    for (const [a, b] of state.diagnostics.unsatisfied_friend_pairs) {
      set.add(a);
      set.add(b);
    }
    return set;
  }, [state.diagnostics.unsatisfied_friend_pairs]);

  const rooms = state.config.flatMap((b) => b.rooms.map((r) => ({ building: b.name, room: r.name })));

  function helpersInCell(building: string, room: string, role: Role): Helper[] {
    return state.assignments
      .filter((a) => a.building === building && a.room === room && a.role === role)
      .map((a) => helpersById.get(a.helper_id))
      .filter((h): h is Helper => h !== undefined);
  }

  async function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over) return;
    const overId = String(over.id);
    if (overId === "unassigned") return; // no unassign; move to Zaloha somewhere instead

    const [building, room, role] = overId.split("::");
    const helperId = Number(active.id);
    setError(null);
    try {
      const next = await api.moveHelper(helperId, building, room, role as Role);
      onStateChange(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function resolve() {
    setBusy(true);
    setError(null);
    try {
      onStateChange(await api.solve());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveManualRoles(next: ManualRoles) {
    try {
      onStateChange(await api.putManualRoles(next));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function setStructural(role: StructuralRole, building: string, room: string | null, helperId: number | null) {
    const filtered = state.manual_roles.structural.filter(
      (s) => !(s.role === role && s.building === building && s.room === room)
    );
    const next: StructuralAssignment[] =
      helperId === null ? filtered : [...filtered, { role, building, room, helper_id: helperId }];
    saveManualRoles({ ...state.manual_roles, structural: next });
  }

  function structuralHelperId(role: StructuralRole, building: string, room: string | null): number | null {
    const entry = state.manual_roles.structural.find(
      (s) => s.role === role && s.building === building && s.room === room
    );
    return entry ? entry.helper_id : null;
  }

  function overlayHelperIds(role: OverlayRole): number[] {
    return state.manual_roles.overlay.filter((o) => o.role === role).map((o) => o.helper_id);
  }

  function addOverlay(role: OverlayRole, helperId: number) {
    saveManualRoles({
      ...state.manual_roles,
      overlay: [...state.manual_roles.overlay, { role, helper_id: helperId }],
    });
  }

  function removeOverlay(role: OverlayRole, helperId: number) {
    saveManualRoles({
      ...state.manual_roles,
      overlay: state.manual_roles.overlay.filter((o) => !(o.role === role && o.helper_id === helperId)),
    });
  }

  if (rooms.length === 0) {
    return (
      <div className="page">
        <p>Configure at least one building with a room first.</p>
      </div>
    );
  }

  return (
    <div className="page">
      <h2>3. Roster</h2>
      <div className="actions">
        <button disabled={busy} onClick={resolve}>
          {state.assignments.length > 0 ? "Re-solve" : "Solve"}
        </button>
        <a className="button-link" href={api.exportUrl()} download>
          Export to Excel
        </a>
      </div>
      {state.diagnostics.status && (
        <p className="hint">
          Status: {state.diagnostics.status}
          {state.diagnostics.objective_value !== null && ` · objective ${state.diagnostics.objective_value}`}
          {" · "}
          {state.diagnostics.unsatisfied_friend_pairs.length} unsatisfied friend request(s)
        </p>
      )}
      {error && <p className="error">{error}</p>}

      <DndContext onDragEnd={handleDragEnd}>
        {unassignedHelpers.length > 0 && (
          <div className="unassigned-pool">
            <strong>Unassigned:</strong>{" "}
            {unassignedHelpers.map((h) => (
              <HelperChip key={h.id} helper={h} unsatisfiedFriend={unsatisfiedHelperIds.has(h.id)} />
            ))}
          </div>
        )}

        <div className="grid-scroll">
          <table className="roster-grid">
            <thead>
              <tr>
                <th></th>
                {state.config.map((b) =>
                  b.rooms.length > 0 ? (
                    <th key={b.name} colSpan={b.rooms.length} className="building-header">
                      {b.name}
                    </th>
                  ) : null
                )}
              </tr>
              <tr>
                <th></th>
                {rooms.map(({ building, room }) => (
                  <th key={`${building}::${room}`}>{room}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ROLES.map((role) => (
                <tr key={role}>
                  <th className="row-label">{ROLE_LABELS[role]}</th>
                  {rooms.map(({ building, room }) => (
                    <Cell key={`${building}::${room}::${role}`} id={`${building}::${room}::${role}`}>
                      {helpersInCell(building, room, role).map((h) => (
                        <HelperChip key={h.id} helper={h} unsatisfiedFriend={unsatisfiedHelperIds.has(h.id)} />
                      ))}
                    </Cell>
                  ))}
                </tr>
              ))}

              {STRUCTURAL_ROLES.filter((r) => r !== "VedouciMistnosti").map((role) => (
                <tr key={role}>
                  <th className="row-label">{STRUCTURAL_LABELS[role]}</th>
                  {state.config.map((b) =>
                    b.rooms.length > 0 ? (
                      <td key={b.name} colSpan={b.rooms.length} className="grid-cell manual-cell">
                        <HelperSelect
                          helpers={state.helpers}
                          value={structuralHelperId(role, b.name, null)}
                          onChange={(id) => setStructural(role, b.name, null, id)}
                        />
                      </td>
                    ) : null
                  )}
                </tr>
              ))}

              <tr>
                <th className="row-label">{STRUCTURAL_LABELS.VedouciMistnosti}</th>
                {rooms.map(({ building, room }) => (
                  <td key={`${building}::${room}::lead`} className="grid-cell manual-cell">
                    <HelperSelect
                      helpers={state.helpers}
                      value={structuralHelperId("VedouciMistnosti", building, room)}
                      onChange={(id) => setStructural("VedouciMistnosti", building, room, id)}
                    />
                  </td>
                ))}
              </tr>

              {OVERLAY_ROLES.map((role) => (
                <tr key={role}>
                  <th className="row-label">{OVERLAY_LABELS[role]}</th>
                  <td colSpan={rooms.length} className="grid-cell manual-cell overlay-cell">
                    {overlayHelperIds(role).map((id) => {
                      const helper = helpersById.get(id);
                      if (!helper) return null;
                      return (
                        <span className="chip removable" key={id}>
                          {helper.name}
                          <button onClick={() => removeOverlay(role, id)}>×</button>
                        </span>
                      );
                    })}
                    <HelperSelect
                      helpers={state.helpers.filter((h) => !overlayHelperIds(role).includes(h.id))}
                      value={null}
                      placeholder="+ add"
                      onChange={(id) => id !== null && addOverlay(role, id)}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DndContext>
    </div>
  );
}

function HelperSelect({
  helpers,
  value,
  onChange,
  placeholder = "—",
}: {
  helpers: Helper[];
  value: number | null;
  onChange: (id: number | null) => void;
  placeholder?: string;
}) {
  return (
    <select
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
    >
      <option value="">{placeholder}</option>
      {helpers.map((h) => (
        <option key={h.id} value={h.id}>
          {h.name}
        </option>
      ))}
    </select>
  );
}
