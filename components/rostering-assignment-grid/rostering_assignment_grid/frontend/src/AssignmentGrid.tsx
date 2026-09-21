import { FrontendRendererArgs } from "@streamlit/component-v2-lib";
import { FC, ReactElement, useMemo, useState } from "react";
import { DndContext } from "@dnd-kit/core";
import type { DragEndEvent } from "@dnd-kit/core";
import { Cell } from "./Cell";
import { HelperChip } from "./HelperChip";
import type { Assignment, AssignmentGridData, AssignmentGridState, FriendCardEntry, Helper, HelperCardData } from "./types";

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
  unsatisfied_friend_pairs,
  satisfied_friend_pairs,
  setTriggerValue,
}): ReactElement => {
  const [hoveredHelperId, setHoveredHelperId] = useState<number | null>(null);

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
  // Maps each helper to the friends they still don't share a room with, in
  // both directions, so hovering either side of an unsatisfied pair can
  // highlight the other.
  const unsatisfiedFriendsOf = useMemo(() => {
    const map = new Map<number, Set<number>>();
    for (const [a, b] of unsatisfied_friend_pairs) {
      if (!map.has(a)) map.set(a, new Set());
      map.get(a)!.add(b);
      if (!map.has(b)) map.set(b, new Set());
      map.get(b)!.add(a);
    }
    return map;
  }, [unsatisfied_friend_pairs]);

  // Helpers with at least one friend request that IS satisfied (the friend
  // is already co-located in the same cell, so no hover-to-find is needed
  // here — unlike the unsatisfied case above).
  const satisfiedHelperIds = useMemo(() => {
    const set = new Set<number>();
    for (const [a, b] of satisfied_friend_pairs) {
      set.add(a);
      set.add(b);
    }
    return set;
  }, [satisfied_friend_pairs]);

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
      roleOrder: roles,
      roleLabels: role_labels,
      sharedFriends,
      differentFriends,
      requestedBy: (requestedByOf.get(h.id) ?? []).map(friendEntry),
    };
  }

  function renderChip(h: Helper) {
    const friendHighlighted =
      hoveredHelperId !== null && hoveredHelperId !== h.id && (unsatisfiedFriendsOf.get(hoveredHelperId)?.has(h.id) ?? false);
    return (
      <HelperChip
        key={h.id}
        helper={h}
        card={cardDataFor(h)}
        unsatisfiedFriend={unsatisfiedFriendsOf.has(h.id)}
        satisfiedFriend={satisfiedHelperIds.has(h.id)}
        friendHighlighted={friendHighlighted}
        onHoverChange={(hovering) => setHoveredHelperId(hovering ? h.id : null)}
      />
    );
  }

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
      .filter((h): h is Helper => h !== undefined)
      .sort((a, b) => a.name.localeCompare(b.name, "cs"));
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
            {roles.map((role) => (
              <tr key={role}>
                <th className="row-label">{role_labels[role] ?? role}</th>
                {rooms.map(({ building, room }) => (
                  <Cell key={`${building}::${room}::${role}`} id={`${building}::${room}::${role}`}>
                    {helpersInCell(building, room, role).map((h) => renderChip(h))}
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
