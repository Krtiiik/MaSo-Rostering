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

// One cell's worth of adjacent rooms *for one specific row* — normally a
// single room, or several if that row's own cells are currently merged
// (see CLAUDE.md "Out-of-solver roles"). The column layout (header rows)
// never merges; only individual rows do, like merging cells within one row
// in Excel.
interface RowGroup {
  building: string;
  rooms: string[];
}

function groupAdjacentRooms(roomNames: string[], mergedPairs: [string, string][]): string[][] {
  const merged = new Set(mergedPairs.map(([a, b]) => `${a}::${b}`));
  const groups: string[][] = [];
  for (const name of roomNames) {
    const last = groups[groups.length - 1];
    if (last && merged.has(`${last[last.length - 1]}::${name}`)) {
      last.push(name);
    } else {
      groups.push([name]);
    }
  }
  return groups;
}

/**
 * The drag-and-drop {building, room} x role grid, plus the non-droppable
 * manual structural/overlay role rows rendered as part of the same table
 * (see CLAUDE.md "Out-of-solver roles"). Drop events, manual-role edits, and
 * cell-merge clicks are reported back to Python via the
 * `drop`/`manual_set`/`cell_merge` triggers — no direct network/API calls,
 * ported from the project's old React app's GridPage.tsx/Cell.tsx/HelperChip.tsx.
 */
const AssignmentGrid: FC<AssignmentGridProps> = ({
  rooms,
  rows,
  helpers,
  assignments,
  manual_entries,
  cell_merges,
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

  // The hover card's role-preference list follows the solver-role rows shown
  // in the grid, minus manual rows (helpers don't rate those) and Záloha
  // (never offered as a choice on the form — see GridRow.preferenceable).
  const roleOrder = useMemo(
    () => rows.filter((r) => r.kind === "role" && r.preferenceable !== false).map((r) => r.key),
    [rows],
  );
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
  // role cells. The column layout is always one column per physical room;
  // only individual rows (see `groupsForRow`) ever merge cells.
  const buildingGroups = useMemo(() => {
    const groups: { building: string; count: number }[] = [];
    for (const r of rooms) {
      const last = groups[groups.length - 1];
      if (last && last.building === r.building) last.count += 1;
      else groups.push({ building: r.building, count: 1 });
    }
    return groups;
  }, [rooms]);

  const roomsByBuilding = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const r of rooms) {
      if (!map.has(r.building)) map.set(r.building, []);
      map.get(r.building)!.push(r.room);
    }
    return map;
  }, [rooms]);

  // This one row's own cell groups, left to right across every building —
  // computed fresh per row from that row's own `cell_merges` entry, so a
  // merge in one row never affects any other row for the same rooms.
  function groupsForRow(rowKey: string): RowGroup[] {
    const result: RowGroup[] = [];
    for (const bg of buildingGroups) {
      const roomNames = roomsByBuilding.get(bg.building) ?? [];
      const pairs = cell_merges[rowKey]?.[bg.building] ?? [];
      for (const group of groupAdjacentRooms(roomNames, pairs)) {
        result.push({ building: bg.building, rooms: group });
      }
    }
    return result;
  }

  function unmergePairsFor(groupRooms: string[]): [string, string][] {
    const pairs: [string, string][] = [];
    for (let i = 0; i < groupRooms.length - 1; i++) pairs.push([groupRooms[i], groupRooms[i + 1]]);
    return pairs;
  }

  function mergeCellRight(rowKey: string, building: string, leftRoom: string, rightRoom: string) {
    setTriggerValue("cell_merge", { key: rowKey, building, pairs: [[leftRoom, rightRoom]], merged: true });
  }

  function unmergeCell(rowKey: string, building: string, groupRooms: string[]) {
    setTriggerValue("cell_merge", { key: rowKey, building, pairs: unmergePairsFor(groupRooms), merged: false });
  }

  function helpersInGroupCell(building: string, groupRooms: string[], role: string): Helper[] {
    return assignments
      .filter((a) => a.building === building && groupRooms.includes(a.room) && a.role === role)
      .map((a) => helpersById.get(a.helper_id))
      .filter((h): h is Helper => h !== undefined)
      .sort((a, b) => a.name.localeCompare(b.name, "cs"));
  }

  function manualEntriesFor(key: string, building: string | null, room: string | null): ManualEntry[] {
    return manual_entries.filter((e) => e.key === key && e.building === building && e.room === room);
  }

  // Room-scope variant: unions entries across every room in a (possibly
  // merged) group, since dropped/typed entries stay keyed to the exact room
  // they belong to even when displayed together in one merged column.
  function manualEntriesForGroup(key: string, building: string, groupRooms: string[]): ManualEntry[] {
    return manual_entries.filter(
      (e) => e.key === key && e.building === building && e.room !== null && groupRooms.includes(e.room),
    );
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over) return;

    const overData = over.data.current as
      | { type?: string; key?: string; building?: string | null; rooms?: string[] | null }
      | undefined;
    if (overData?.type === "duplicate" && overData.key) {
      const helperId = Number(active.id);
      const loc = assignmentByHelper.get(helperId);
      // Should already be unreachable (the cell disables itself for a
      // mismatched location), but guard against it directly too. A null
      // `overData.rooms` means this is a building-scoped cell (Registrace)
      // — matched on building alone; a non-null `rooms` matches if the
      // helper's own room is any one of them (more than one room means the
      // underlying columns are currently merged).
      const roomOk = overData.rooms == null || (!!loc && overData.rooms.includes(loc.room));
      if (!loc || loc.building !== overData.building || !roomOk) return;
      const helper = helpersById.get(helperId);
      if (!helper) return;
      // The canonical room a *new* entry is stored under is the group's
      // first room — existing entries can be scattered across the group's
      // other rooms though (e.g. entered before two rooms were merged), so
      // the dedup/display list below unions across the whole group.
      const canonicalRoom = overData.rooms == null ? null : overData.rooms[0];
      const existingNames = (
        overData.rooms == null
          ? manualEntriesFor(overData.key, overData.building ?? null, null)
          : manualEntriesForGroup(overData.key, overData.building!, overData.rooms)
      ).map((e) => e.name);
      if (existingNames.includes(helper.name)) return;
      setTriggerValue("manual_set", {
        key: overData.key,
        building: overData.building ?? null,
        room: canonicalRoom,
        names: [...existingNames, helper.name],
      });
      return;
    }

    const overId = String(over.id);
    if (overId === "unassigned") return; // no unassign; move to Zaloha somewhere instead

    const [building, room, role] = overId.split("::");
    const helperId = Number(active.id);
    setTriggerValue("drop", { helper_id: helperId, building, room, role });
  }

  function renderManualRow(
    key: string,
    scope: "building" | "room" | "global",
    plainText: boolean,
    singleEntry: boolean,
    allowDuplicateDrop: boolean,
  ): ReactNode {
    if (scope === "room") {
      const groups = groupsForRow(key);
      return groups.map((group, idx) => {
        const next = groups[idx + 1];
        const canMergeRight = !!next && next.building === group.building;
        return (
          <ManualCell
            key={`${group.building}::${group.rooms.join("+")}::${key}`}
            entries={manualEntriesForGroup(key, group.building, group.rooms)}
            colSpan={group.rooms.length}
            datalistId={plainText ? undefined : datalistId}
            singleEntry={singleEntry}
            onChange={(names) => setTriggerValue("manual_set", { key, building: group.building, room: group.rooms[0], names })}
            dropId={allowDuplicateDrop ? `duplicate::${key}::${group.building}::${group.rooms[0]}` : undefined}
            manualKey={key}
            building={group.building}
            rooms={allowDuplicateDrop ? group.rooms : null}
            helperLocations={allowDuplicateDrop ? assignmentByHelper : undefined}
            onMergeRight={canMergeRight ? () => mergeCellRight(key, group.building, group.rooms[group.rooms.length - 1], next!.rooms[0]) : undefined}
            onUnmerge={group.rooms.length > 1 ? () => unmergeCell(key, group.building, group.rooms) : undefined}
          />
        );
      });
    }
    if (scope === "global") {
      return (
        <ManualCell
          key={`global::${key}`}
          entries={manualEntriesFor(key, null, null)}
          colSpan={rooms.length}
          datalistId={plainText ? undefined : datalistId}
          singleEntry={singleEntry}
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
        singleEntry={singleEntry}
        onChange={(names) => setTriggerValue("manual_set", { key, building: g.building, room: null, names })}
        dropId={allowDuplicateDrop ? `duplicate::${key}::${g.building}` : undefined}
        manualKey={key}
        building={g.building}
        rooms={null}
        helperLocations={allowDuplicateDrop ? assignmentByHelper : undefined}
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
                  ? groupsForRow(rowDef.key).map((group, idx, groups) => {
                      const next = groups[idx + 1];
                      const canMergeRight = !!next && next.building === group.building;
                      return (
                        <Cell
                          key={`${group.building}::${group.rooms.join("+")}::${rowDef.key}`}
                          id={`${group.building}::${group.rooms[0]}::${rowDef.key}`}
                          colSpan={group.rooms.length}
                          onMergeRight={
                            canMergeRight
                              ? () => mergeCellRight(rowDef.key, group.building, group.rooms[group.rooms.length - 1], next!.rooms[0])
                              : undefined
                          }
                          onUnmerge={group.rooms.length > 1 ? () => unmergeCell(rowDef.key, group.building, group.rooms) : undefined}
                        >
                          {helpersInGroupCell(group.building, group.rooms, rowDef.key).map((h) => renderChip(h))}
                        </Cell>
                      );
                    })
                  : renderManualRow(
                      rowDef.key,
                      rowDef.scope ?? "global",
                      rowDef.plain_text ?? false,
                      rowDef.single_entry ?? false,
                      rowDef.allowDuplicateDrop ?? false,
                    )}
              </tr>
            ))}
          </tbody>
        </table>
      </DndContext>
    </div>
  );
};

export default AssignmentGrid;
