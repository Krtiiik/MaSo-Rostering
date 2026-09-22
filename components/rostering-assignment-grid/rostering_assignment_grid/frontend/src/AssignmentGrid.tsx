import { FrontendRendererArgs } from "@streamlit/component-v2-lib";
import { FC, ReactElement, ReactNode, useId, useMemo, useState } from "react";
import { DndContext } from "@dnd-kit/core";
import type { DragEndEvent } from "@dnd-kit/core";
import { Cell } from "./Cell";
import { HelperChip } from "./HelperChip";
import { ManualCell } from "./ManualCell";
import type {
  Assignment,
  AssignmentGridData,
  AssignmentGridState,
  FriendCardEntry,
  Helper,
  HelperCardData,
  ManualEntry,
} from "./types";

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
  setTriggerValue,
}): ReactElement => {
  const [hoveredHelperId, setHoveredHelperId] = useState<number | null>(null);
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

  // Every friend-relation signal below is derived directly from each
  // helper's own `friends` list (the raw, resolved-to-id requests from
  // ingestion) plus current assignments — deliberately NOT from the
  // solver's satisfied/unsatisfied_friend_pairs diagnostics, which are
  // collapsed by the friend-scoring config's mode/symmetric settings and
  // can silently merge or drop a one-directional request. A request A
  // named but B didn't reciprocate must stay asymmetric here.
  const sameRoom = (aId: number, bId: number) => {
    const a = assignmentByHelper.get(aId);
    const b = assignmentByHelper.get(bId);
    return !!a && !!b && a.building === b.building && a.room === b.room;
  };

  // Maps each helper to the friends THEY named, directed, with whether that
  // specific request is satisfied (co-located) — so hovering a helper
  // reveals each of their own requests individually, wherever placed.
  const friendsOf = useMemo(() => {
    const map = new Map<number, Map<number, boolean>>();
    for (const h of helpers) {
      for (const friendId of h.friends) {
        if (friendId === h.id || !helpersById.has(friendId)) continue;
        if (!map.has(h.id)) map.set(h.id, new Map());
        map.get(h.id)!.set(friendId, sameRoom(h.id, friendId));
      }
    }
    return map;
  }, [helpers, helpersById, assignmentByHelper]);

  // Reverse index: who named THEM. Used to highlight, on hover, the other
  // helpers who requested the hovered one — independent of whether the
  // hovered helper requested them back.
  const requestersOf = useMemo(() => {
    const map = new Map<number, Set<number>>();
    for (const h of helpers) {
      for (const friendId of h.friends) {
        if (friendId === h.id || !helpersById.has(friendId)) continue;
        if (!map.has(friendId)) map.set(friendId, new Set());
        map.get(friendId)!.add(h.id);
      }
    }
    return map;
  }, [helpers, helpersById]);

  // A helper gets the persistent "unsatisfied" marker if at least one
  // friend THEY named isn't currently co-located with them.
  const unsatisfiedHelperIds = useMemo(() => {
    const set = new Set<number>();
    for (const [helperId, targets] of friendsOf) {
      for (const satisfied of targets.values()) {
        if (!satisfied) {
          set.add(helperId);
          break;
        }
      }
    }
    return set;
  }, [friendsOf]);

  // Reverse of each helper's `friends` list — who named THEM, so the hover
  // card can show "requested by" separately from the helper's own requests.
  const requestedByOf = useMemo(() => {
    const map = new Map<number, number[]>();
    for (const h of helpers) {
      for (const friendId of h.friends) {
        if (!map.has(friendId)) map.set(friendId, []);
        map.get(friendId)!.push(h.id);
      }
    }
    return map;
  }, [helpers]);

  // The hover card's role-preference list follows the same solver-role rows
  // shown in the grid (manual rows excluded — helpers don't rate those).
  const roleOrder = useMemo(() => rows.filter((r) => r.kind === "role").map((r) => r.key), [rows]);
  const roleLabels = useMemo(
    () => Object.fromEntries(rows.filter((r) => r.kind === "role").map((r) => [r.key, r.label])),
    [rows],
  );

  function friendEntry(id: number): FriendCardEntry {
    return { id, name: helpersById.get(id)?.name ?? `#${id}` };
  }

  function isColocated(a: number, b: number): boolean {
    const roomA = assignmentByHelper.get(a);
    const roomB = assignmentByHelper.get(b);
    return !!roomA && !!roomB && roomA.building === roomB.building && roomA.room === roomB.room;
  }

  function cardDataFor(h: Helper): HelperCardData {
    const sharedFriends: FriendCardEntry[] = [];
    const differentFriends: FriendCardEntry[] = [];
    for (const friendId of h.friends) {
      (isColocated(h.id, friendId) ? sharedFriends : differentFriends).push(friendEntry(friendId));
    }
    return {
      helper: h,
      roleOrder,
      roleLabels,
      sharedFriends,
      differentFriends,
      requestedBy: (requestedByOf.get(h.id) ?? []).map(friendEntry),
    };
  }

  function renderChip(h: Helper) {
    let friendHighlight: "satisfied" | "unsatisfied" | "requester" | undefined;
    if (hoveredHelperId !== null && hoveredHelperId !== h.id) {
      const status = friendsOf.get(hoveredHelperId)?.get(h.id);
      if (status !== undefined) {
        friendHighlight = status ? "satisfied" : "unsatisfied";
      } else if (requestersOf.get(hoveredHelperId)?.has(h.id)) {
        friendHighlight = "requester";
      }
    }
    return (
      <HelperChip
        key={h.id}
        helper={h}
        card={cardDataFor(h)}
        unsatisfiedFriend={unsatisfiedHelperIds.has(h.id)}
        friendHighlight={friendHighlight}
        onHoverChange={(hovering) => setHoveredHelperId(hovering ? h.id : null)}
      />
    );
  }

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

  function renderManualRow(key: string, scope: "building" | "room" | "global", plainText: boolean): ReactNode {
    if (scope === "room") {
      return rooms.map(({ building, room }) => (
        <ManualCell
          key={`${building}::${room}::${key}`}
          entries={manualEntriesFor(key, building, room)}
          colSpan={1}
          datalistId={plainText ? undefined : datalistId}
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
          datalistId={plainText ? undefined : datalistId}
          onChange={(names) => setTriggerValue("manual_set", { key, building: null, room: null, names })}
        />
      );
    }
    return buildingGroups.map((g) => (
      <ManualCell
        key={`${g.building}::${key}`}
        entries={manualEntriesFor(key, g.building, null)}
        colSpan={g.count}
        datalistId={plainText ? undefined : datalistId}
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
            {unassignedHelpers.map((h) => renderChip(h))}
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
                        {helpersInCell(building, room, rowDef.key).map((h) => renderChip(h))}
                      </Cell>
                    ))
                  : renderManualRow(rowDef.key, rowDef.scope ?? "global", rowDef.plain_text ?? false)}
              </tr>
            ))}
          </tbody>
        </table>
      </DndContext>
    </div>
  );
};

export default AssignmentGrid;
