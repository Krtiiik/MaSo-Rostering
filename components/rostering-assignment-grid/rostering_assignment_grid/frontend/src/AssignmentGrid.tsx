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
  RoomGroup,
} from "./types";

export type AssignmentGridProps = Pick<
  FrontendRendererArgs<AssignmentGridState, AssignmentGridData>,
  "setTriggerValue"
> &
  AssignmentGridData;

// One column-layout entry: either a room group (a normal data column) or a
// clickable divider between two adjacent groups in the same building (see
// CLAUDE.md "Out-of-solver roles" — clicking a divider merges the two
// columns it sits between; clicking a merged group's header splits it back
// apart). Buildings never share a divider between them — only rooms within
// the same building can be merged.
type ColumnItem =
  | { kind: "group"; group: RoomGroup }
  | { kind: "divider"; building: string; leftRoom: string; rightRoom: string };

/**
 * The drag-and-drop {building, room} x role grid, plus the non-droppable
 * manual structural/overlay role rows rendered as part of the same table
 * (see CLAUDE.md "Out-of-solver roles"). Drop events, manual-role edits, and
 * room-merge clicks are reported back to Python via the
 * `drop`/`manual_set`/`room_merge` triggers — no direct network/API calls,
 * ported from the project's old React app's GridPage.tsx/Cell.tsx/HelperChip.tsx.
 */
const AssignmentGrid: FC<AssignmentGridProps> = ({
  room_groups,
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

  // room_groups (one entry per column — normally one room, or several if
  // merged) interleaved with a clickable divider between every pair of
  // adjacent groups that share a building (clicking one merges that pair;
  // see CLAUDE.md "Out-of-solver roles"). Buildings never share a divider.
  const columnLayout = useMemo(() => {
    const items: ColumnItem[] = [];
    for (let i = 0; i < room_groups.length; i++) {
      const group = room_groups[i];
      items.push({ kind: "group", group });
      const next = room_groups[i + 1];
      if (next && next.building === group.building) {
        items.push({
          kind: "divider",
          building: group.building,
          leftRoom: group.rooms[group.rooms.length - 1],
          rightRoom: next.rooms[0],
        });
      }
    }
    return items;
  }, [room_groups]);

  // Consecutive column-layout entries (groups + their interleaved dividers)
  // sharing a building group into one building header cell spanning them —
  // also used for building-scoped manual role cells, whose colSpan must
  // likewise cover any divider columns within that building's span.
  const buildingGroups = useMemo(() => {
    const groups: { building: string; count: number }[] = [];
    for (const item of columnLayout) {
      const building = item.kind === "group" ? item.group.building : item.building;
      const last = groups[groups.length - 1];
      if (last && last.building === building) last.count += 1;
      else groups.push({ building, count: 1 });
    }
    return groups;
  }, [columnLayout]);

  function unmergePairs(group: RoomGroup): [string, string][] {
    const pairs: [string, string][] = [];
    for (let i = 0; i < group.rooms.length - 1; i++) pairs.push([group.rooms[i], group.rooms[i + 1]]);
    return pairs;
  }

  function mergeDivider(item: Extract<ColumnItem, { kind: "divider" }>) {
    setTriggerValue("room_merge", { building: item.building, pairs: [[item.leftRoom, item.rightRoom]], merged: true });
  }

  function unmergeGroup(group: RoomGroup) {
    setTriggerValue("room_merge", { building: group.building, pairs: unmergePairs(group), merged: false });
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

  function dividerProps(item: Extract<ColumnItem, { kind: "divider" }>) {
    return {
      className: "room-divider",
      title: "Click to merge these two columns",
      onClick: () => mergeDivider(item),
    };
  }

  function renderManualRow(key: string, scope: "building" | "room" | "global", allowDuplicateDrop: boolean): ReactNode {
    if (scope === "room") {
      return columnLayout.map((item, idx) =>
        item.kind === "divider" ? (
          <td key={`divider::${idx}`} {...dividerProps(item)} />
        ) : (
          <ManualCell
            key={`${item.group.building}::${item.group.rooms.join("+")}::${key}`}
            entries={manualEntriesForGroup(key, item.group.building, item.group.rooms)}
            colSpan={1}
            datalistId={datalistId}
            onChange={(names) =>
              setTriggerValue("manual_set", { key, building: item.group.building, room: item.group.rooms[0], names })
            }
            dropId={allowDuplicateDrop ? `duplicate::${key}::${item.group.building}::${item.group.rooms[0]}` : undefined}
            manualKey={key}
            building={item.group.building}
            rooms={allowDuplicateDrop ? item.group.rooms : null}
            helperLocations={allowDuplicateDrop ? assignmentByHelper : undefined}
          />
        ),
      );
    }
    if (scope === "global") {
      return (
        <ManualCell
          key={`global::${key}`}
          entries={manualEntriesFor(key, null, null)}
          colSpan={columnLayout.length}
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
        dropId={allowDuplicateDrop ? `duplicate::${key}::${g.building}` : undefined}
        manualKey={key}
        building={g.building}
        rooms={null}
        helperLocations={allowDuplicateDrop ? assignmentByHelper : undefined}
      />
    ));
  }

  if (room_groups.length === 0) {
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
              {columnLayout.map((item, idx) =>
                item.kind === "divider" ? (
                  <th key={`divider::${idx}`} {...dividerProps(item)} />
                ) : (
                  <th
                    key={`${item.group.building}::${item.group.rooms.join("+")}`}
                    className={item.group.rooms.length > 1 ? "room-header merged" : "room-header"}
                    title={item.group.rooms.length > 1 ? "Click to split these rooms back apart" : undefined}
                    onClick={item.group.rooms.length > 1 ? () => unmergeGroup(item.group) : undefined}
                  >
                    {item.group.rooms.join(" + ")}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((rowDef) => (
              <tr key={`${rowDef.kind}::${rowDef.key}`}>
                <th className="row-label">{rowDef.label}</th>
                {rowDef.kind === "role"
                  ? columnLayout.map((item, idx) =>
                      item.kind === "divider" ? (
                        <td key={`divider::${idx}`} {...dividerProps(item)} />
                      ) : (
                        <Cell
                          key={`${item.group.building}::${item.group.rooms.join("+")}::${rowDef.key}`}
                          id={`${item.group.building}::${item.group.rooms[0]}::${rowDef.key}`}
                        >
                          {helpersInGroupCell(item.group.building, item.group.rooms, rowDef.key).map((h) => renderChip(h))}
                        </Cell>
                      ),
                    )
                  : renderManualRow(rowDef.key, rowDef.scope ?? "global", rowDef.allowDuplicateDrop ?? false)}
              </tr>
            ))}
          </tbody>
        </table>
      </DndContext>
    </div>
  );
};

export default AssignmentGrid;
