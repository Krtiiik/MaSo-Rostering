import { FrontendRendererArgs } from "@streamlit/component-v2-lib";
import { FC, ReactElement, ReactNode, useId, useMemo } from "react";
import { DndContext } from "@dnd-kit/core";
import type { DragEndEvent } from "@dnd-kit/core";
import { Cell } from "./Cell";
import { HelperChip } from "./HelperChip";
import { ManualCell } from "./ManualCell";
import type { Assignment, AssignmentGridData, AssignmentGridState, Helper, ManualEntry } from "./types";

export type AssignmentGridProps = Pick<
  FrontendRendererArgs<AssignmentGridState, AssignmentGridData>,
  "setTriggerValue"
> &
  AssignmentGridData;

/**
 * The drag-and-drop {building, room} x role grid, plus the non-droppable
 * manual structural/overlay role rows rendered as part of the same table
 * (see CLAUDE.md "Out-of-solver roles"). Drop events and manual-role edits
 * are reported back to Python via the `drop`/`manual_set` triggers — no
 * direct network/API calls, ported from the project's old React app's
 * GridPage.tsx/Cell.tsx/HelperChip.tsx.
 */
const AssignmentGrid: FC<AssignmentGridProps> = ({
  rooms,
  rows,
  helpers,
  assignments,
  manual_entries,
  helper_names,
  unsatisfied_helper_ids,
  setTriggerValue,
}): ReactElement => {
  const datalistId = useId();

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

  const unassignedHelpers = helpers
    .filter((h) => !assignmentByHelper.has(h.id))
    .sort((a, b) => a.name.localeCompare(b.name, "cs"));
  const unsatisfiedSet = useMemo(() => new Set(unsatisfied_helper_ids), [unsatisfied_helper_ids]);

  // Consecutive rooms sharing a building (the order the Python side sends
  // them in, following the buildings/rooms config) group into one building
  // header cell spanning its rooms — also used for building-scoped manual
  // role cells.
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
      .filter((h): h is Helper => h !== undefined)
      .sort((a, b) => a.name.localeCompare(b.name, "cs"));
  }

  function manualEntriesFor(key: string, building: string | null, room: string | null): ManualEntry[] {
    return manual_entries.filter((e) => e.key === key && e.building === building && e.room === room);
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

  function renderManualRow(key: string, scope: "building" | "room" | "global"): ReactNode {
    if (scope === "room") {
      return rooms.map(({ building, room }) => (
        <ManualCell
          key={`${building}::${room}::${key}`}
          entries={manualEntriesFor(key, building, room)}
          colSpan={1}
          datalistId={datalistId}
          onChange={(names) => setTriggerValue("manual_set", { key, building, room, names })}
        />
      ));
    }
    if (scope === "global") {
      return (
        <ManualCell
          key={`global::${key}`}
          entries={manualEntriesFor(key, null, null)}
          colSpan={rooms.length}
          datalistId={datalistId}
          onChange={(names) => setTriggerValue("manual_set", { key, building: null, room: null, names })}
        />
      );
    }
    return buildingGroups.map((g) => (
      <ManualCell
        key={`${g.building}::${key}`}
        entries={manualEntriesFor(key, g.building, null)}
        colSpan={g.count}
        datalistId={datalistId}
        onChange={(names) => setTriggerValue("manual_set", { key, building: g.building, room: null, names })}
      />
    ));
  }

  if (rooms.length === 0) {
    return <p>Configure at least one building with a room first.</p>;
  }

  return (
    <div className="grid-scroll">
      <datalist id={datalistId}>
        {helper_names.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>
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
            {rows.map((rowDef) => (
              <tr key={`${rowDef.kind}::${rowDef.key}`}>
                <th className="row-label">{rowDef.label}</th>
                {rowDef.kind === "role"
                  ? rooms.map(({ building, room }) => (
                      <Cell key={`${building}::${room}::${rowDef.key}`} id={`${building}::${room}::${rowDef.key}`}>
                        {helpersInCell(building, room, rowDef.key).map((h) => (
                          <HelperChip key={h.id} helper={h} unsatisfiedFriend={unsatisfiedSet.has(h.id)} />
                        ))}
                      </Cell>
                    ))
                  : renderManualRow(rowDef.key, rowDef.scope ?? "global")}
              </tr>
            ))}
          </tbody>
        </table>
      </DndContext>
    </div>
  );
};

export default AssignmentGrid;
