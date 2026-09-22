import { useDraggable } from "@dnd-kit/core";
import { useEffect, useRef, useState } from "react";
import type { MouseEvent } from "react";
import type { Helper, HelperCardData } from "./types";
import { HelperCard } from "./HelperCard";

interface Props {
  helper: Helper;
  card: HelperCardData;
  unsatisfiedFriend?: boolean;
  friendHighlight?: "satisfied" | "unsatisfied" | "requester";
  onHoverChange?: (hovering: boolean) => void;
}

const HOVER_DELAY_MS = 400;
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

export function HelperChip({ helper, card, unsatisfiedFriend, friendHighlight, onHoverChange }: Props) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: String(helper.id),
  });
  const [cardPosition, setCardPosition] = useState<{ top: number; left: number } | null>(null);
  const hoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mousePosRef = useRef<{ x: number; y: number } | null>(null);

  useEffect(
    () => () => {
      if (hoverTimerRef.current !== null) clearTimeout(hoverTimerRef.current);
    },
    [],
  );

  const style = transform
    ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`, zIndex: 10 }
    : undefined;

  const highlightClass = friendHighlight ? ` friend-highlight-${friendHighlight}` : "";

  // The card shows after a short hover delay (so it doesn't flash while
  // skimming across the grid) anchored to wherever the cursor ended up, then
  // tracks the cursor — via `position: fixed`, which escapes the grid's
  // scrollable-table clipping (overflow-x: auto on an ancestor forces
  // overflow-y: auto too, which would otherwise clip an absolutely-
  // positioned popover) regardless of where in the table the chip sits.
  function handleMouseEnter(event: MouseEvent<HTMLDivElement>) {
    onHoverChange?.(true);
    mousePosRef.current = { x: event.clientX, y: event.clientY };
    hoverTimerRef.current = setTimeout(() => {
      if (mousePosRef.current) setCardPosition(computeCardPosition(mousePosRef.current.x, mousePosRef.current.y));
    }, HOVER_DELAY_MS);
  }

  function handleMouseMove(event: MouseEvent<HTMLDivElement>) {
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
    setCardPosition(null);
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      className={`helper-chip${isDragging ? " dragging" : ""}${unsatisfiedFriend ? " unsatisfied" : ""}${highlightClass}`}
      title={unsatisfiedFriend ? "Has an unsatisfied friend request" : undefined}
      onMouseEnter={handleMouseEnter}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
    >
      {helper.name}
      {helper.can_bring_notebook && <span title="Can bring a notebook"> 💻</span>}
      {helper.can_bring_camera && <span title="Can bring a camera"> 📷</span>}
      {cardPosition && !isDragging && <HelperCard data={card} top={cardPosition.top} left={cardPosition.left} />}
    </div>
  );
}
