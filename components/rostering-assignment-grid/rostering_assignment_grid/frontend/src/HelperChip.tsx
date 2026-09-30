import { useDraggable } from "@dnd-kit/core";
import { useEffect, useRef, useState } from "react";
import type { MouseEvent } from "react";
import type { Helper, HelperCardData, TagPill } from "./types";
import { HelperCard } from "./HelperCard";

// Black or white, whichever reads better on the given "#rrggbb" fill (the same
// rule as rostering.streamlit_app.tag_pills).
function pillTextColour(hex: string): string {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return (r * 299 + g * 587 + b * 114) / 1000 > 150 ? "#000000" : "#ffffff";
}

export function TagPillView({ pill, implied }: { pill: TagPill; implied: boolean }) {
  const colour = /^#[0-9a-fA-F]{6}$/.test(pill.colour) ? pill.colour : "#888888";
  const style = implied
    ? { borderColor: colour, color: colour }
    : { borderColor: colour, background: colour, color: pillTextColour(colour) };
  return (
    <span className={`tag-pill ${implied ? "tag-pill-implied" : "tag-pill-direct"}`} style={style}>
      {pill.name}
    </span>
  );
}

interface Props {
  helper: Helper;
  card: HelperCardData;
  // Show the Helper's Tag pills under their name.
  showTags?: boolean;
  // Faded by the Tag filter (still in place, still draggable).
  dimmed?: boolean;
  unsatisfiedFriend?: boolean;
  friendHighlight?: "satisfied" | "unsatisfied" | "requester";
  onHoverChange?: (hovering: boolean) => void;
  // The Broken-rule lines this chip is part of, if any — marks it lightly.
  broken?: string[];
  // Lock state of a placed Helper's Assignment; `onToggleLock` is given only
  // for a placed chip (ctrl/cmd-click and the hover card's button use it).
  locked?: boolean;
  onToggleLock?: () => void;
}

const HOVER_DELAY_MS = 400;
// Leaving the chip hides the card only after this grace period, so the cursor
// can cross the small gap onto the card (to reach its Lock button).
const HIDE_DELAY_MS = 250;
const CARD_WIDTH = 260;
// The card's real height varies with content (role/friend list length); this
// is just an estimate used to decide whether to flip above/left of the
// cursor so the card doesn't render off-screen.
const CARD_HEIGHT_ESTIMATE = 260;
const CURSOR_OFFSET = 14;
const VIEWPORT_MARGIN = 8;

// Anchors one corner of the card to the cursor tip, flipping to the
// opposite side of the cursor on either axis if the card would otherwise
// overflow the viewport.
function computeCardPosition(clientX: number, clientY: number): { top: number; left: number } {
  let left = clientX + CURSOR_OFFSET;
  if (left + CARD_WIDTH + VIEWPORT_MARGIN > window.innerWidth) {
    left = clientX - CURSOR_OFFSET - CARD_WIDTH;
  }
  left = Math.max(VIEWPORT_MARGIN, left);

  let top = clientY + CURSOR_OFFSET;
  if (top + CARD_HEIGHT_ESTIMATE + VIEWPORT_MARGIN > window.innerHeight) {
    top = clientY - CURSOR_OFFSET - CARD_HEIGHT_ESTIMATE;
  }
  top = Math.max(VIEWPORT_MARGIN, top);

  return { top, left };
}

export function HelperChip({
  helper,
  card,
  showTags,
  dimmed,
  unsatisfiedFriend,
  friendHighlight,
  onHoverChange,
  broken,
  locked,
  onToggleLock,
}: Props) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: String(helper.id),
  });
  const [cardPosition, setCardPosition] = useState<{ top: number; left: number } | null>(null);
  const hoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mousePosRef = useRef<{ x: number; y: number } | null>(null);

  useEffect(
    () => () => {
      if (hoverTimerRef.current !== null) clearTimeout(hoverTimerRef.current);
      if (hideTimerRef.current !== null) clearTimeout(hideTimerRef.current);
    },
    [],
  );

  function cancelHide() {
    if (hideTimerRef.current !== null) {
      clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }
  }

  const style = transform
    ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`, zIndex: 10 }
    : undefined;

  const titleText =
    [...(broken ?? []), ...(unsatisfiedFriend ? ["Has an unsatisfied friend request"] : [])].join("\n") || undefined;

  const highlightClass = friendHighlight ? ` friend-highlight-${friendHighlight}` : "";

  // The card shows after a short hover delay (so it doesn't flash while
  // skimming across the grid) anchored to wherever the cursor ended up, then
  // tracks the cursor — via `position: fixed`, which escapes the grid's
  // scrollable-table clipping (overflow-x: auto on an ancestor forces
  // overflow-y: auto too, which would otherwise clip an absolutely-
  // positioned popover) regardless of where in the table the chip sits.
  function handleMouseEnter(event: MouseEvent<HTMLDivElement>) {
    onHoverChange?.(true);
    cancelHide();
    // Coming back onto the (already shown) card keeps it where it is.
    if (cardPosition) return;
    mousePosRef.current = { x: event.clientX, y: event.clientY };
    hoverTimerRef.current = setTimeout(() => {
      if (mousePosRef.current) setCardPosition(computeCardPosition(mousePosRef.current.x, mousePosRef.current.y));
    }, HOVER_DELAY_MS);
  }

  function handleMouseMove(event: MouseEvent<HTMLDivElement>) {
    // Moving over the card itself (it is a child of the chip) must not drag it
    // away from the cursor, or its Lock button could never be reached.
    if ((event.target as HTMLElement).closest(".helper-card")) return;
    mousePosRef.current = { x: event.clientX, y: event.clientY };
    if (cardPosition) {
      setCardPosition(computeCardPosition(event.clientX, event.clientY));
    }
  }

  function handleMouseLeave() {
    onHoverChange?.(false);
    mousePosRef.current = null;
    if (hoverTimerRef.current !== null) {
      clearTimeout(hoverTimerRef.current);
      hoverTimerRef.current = null;
    }
    if (!cardPosition) return;
    cancelHide();
    hideTimerRef.current = setTimeout(() => {
      hideTimerRef.current = null;
      setCardPosition(null);
    }, HIDE_DELAY_MS);
  }

  // ctrl/cmd-click toggles the lock; a plain click (and a drag, which the
  // grid's activation distance keeps apart from a click) does nothing.
  function handleClick(event: MouseEvent<HTMLDivElement>) {
    if (!onToggleLock || !(event.ctrlKey || event.metaKey)) return;
    event.preventDefault();
    onToggleLock();
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      className={`helper-chip${isDragging ? " dragging" : ""}${unsatisfiedFriend ? " unsatisfied" : ""}${broken?.length ? " broken" : ""}${locked ? " locked" : ""}${dimmed ? " dimmed" : ""}${highlightClass}`}
      title={titleText}
      onClick={handleClick}
      onMouseEnter={handleMouseEnter}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
    >
      {locked && (
        <span className="helper-chip-lock" title="Locked: a full Solve keeps this Assignment">
          🔒{" "}
        </span>
      )}
      {helper.name}
      {helper.can_bring_notebook && <span title="Can bring a notebook"> 💻</span>}
      {helper.can_bring_camera && <span title="Can bring a camera"> 📷</span>}
      {showTags && helper.tags && (helper.tags.direct.length > 0 || helper.tags.implied.length > 0) && (
        <div className="helper-chip-tags">
          {helper.tags.direct.map((pill) => (
            <TagPillView key={`d:${pill.name}`} pill={pill} implied={false} />
          ))}
          {helper.tags.implied.map((pill) => (
            <TagPillView key={`i:${pill.name}`} pill={pill} implied={true} />
          ))}
        </div>
      )}
      {cardPosition && !isDragging && (
        <HelperCard
          data={card}
          top={cardPosition.top}
          left={cardPosition.left}
          locked={locked}
          onToggleLock={onToggleLock}
        />
      )}
    </div>
  );
}
