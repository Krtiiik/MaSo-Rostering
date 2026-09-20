import { FrontendRendererArgs } from "@streamlit/component-v2-lib";
import { FC, ReactElement, useMemo } from "react";
import { DndContext } from "@dnd-kit/core";
import type { DragEndEvent } from "@dnd-kit/core";
import { Cell } from "./Cell";
import { HelperChip } from "./HelperChip";
import type { Assignment, AssignmentGridData, AssignmentGridState, Helper } from "./types";

export type AssignmentGridProps = Pick<
  FrontendRendererArgs<AssignmentGridState, AssignmentGridData>,
  "setTriggerValue"
> &
  AssignmentGridData;

/**
 * The drag-and-drop {building, room} x role grid. Pure presentation plus
 * drop events reported back to Python via the `drop` trigger — no direct
 * network/API calls, ported from the project's old React app's
 * GridPage.tsx/Cell.tsx/HelperChip.tsx.
 */
const AssignmentGrid: FC<AssignmentGridProps> = ({
  rooms,
  roles,
  role_labels,
  helpers,
  assignments,
  unsatisfied_helper_ids,
  setTriggerValue,
}): ReactElement => {
  const helpersById = useMemo(() => {
    const map = new Map<number, Helper>();
    for (const h of helpers) map.set(h.id, h);
    return map;
  }, [helpers]);

  const assignmentByHelper = useMemo(() => {
    const map = new Map<number, Assignment>();
    for (const a of assignments) map.set(a.helper_id, a);
    return map;
  }, [assignments]);

  const unassignedHelpers = helpers.filter((h) => !assignmentByHelper.has(h.id));
  const unsatisfiedSet = useMemo(() => new Set(unsatisfied_helper_ids), [unsatisfied_helper_ids]);

  // Consecutive rooms sharing a building (the order the Python side sends
  // them in, following the buildings/rooms config) group into one building
  // header cell spanning its rooms.
  const buildingGroups = useMemo(() => {
    const groups: { building: string; count: number }[] = [];
    for (const r of rooms) {
      const last = groups[groups.length - 1];
      if (last && last.building === r.building) last.count += 1;
      else groups.push({ building: r.building, count: 1 });
    }
    return groups;
  }, [rooms]);

  function helpersInCell(building: string, room: string, role: string): Helper[] {
    return assignments
      .filter((a) => a.building === building && a.room === room && a.role === role)
      .map((a) => helpersById.get(a.helper_id))
      .filter((h): h is Helper => h !== undefined);
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over) return;
    const overId = String(over.id);
    if (overId === "unassigned") return; // no unassign; move to Zaloha somewhere instead

    const [building, room, role] = overId.split("::");
    const helperId = Number(active.id);
    setTriggerValue("drop", { helper_id: helperId, building, room, role });
  }

  if (rooms.length === 0) {
    return <p>Configure at least one building with a room first.</p>;
  }

  return (
    <div className="grid-scroll">
      <DndContext onDragEnd={handleDragEnd}>
        {unassignedHelpers.length > 0 && (
          <div className="unassigned-pool">
            <strong>Unassigned:</strong>{" "}
            {unassignedHelpers.map((h) => (
              <HelperChip key={h.id} helper={h} unsatisfiedFriend={unsatisfiedSet.has(h.id)} />
            ))}
          </div>
        )}

        <table className="roster-grid">
          <thead>
            <tr>
              <th></th>
              {buildingGroups.map((g) => (
                <th key={g.building} colSpan={g.count} className="building-header">
                  {g.building}
                </th>
              ))}
            </tr>
            <tr>
              <th></th>
              {rooms.map(({ building, room }) => (
                <th key={`${building}::${room}`}>{room}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {roles.map((role) => (
              <tr key={role}>
                <th className="row-label">{role_labels[role] ?? role}</th>
                {rooms.map(({ building, room }) => (
                  <Cell key={`${building}::${room}::${role}`} id={`${building}::${room}::${role}`}>
                    {helpersInCell(building, room, role).map((h) => (
                      <HelperChip key={h.id} helper={h} unsatisfiedFriend={unsatisfiedSet.has(h.id)} />
                    ))}
                  </Cell>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </DndContext>
    </div>
  );
};

export default AssignmentGrid;
