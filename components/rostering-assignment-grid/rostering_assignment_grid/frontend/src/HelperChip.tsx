import { useDraggable } from "@dnd-kit/core";
import { useState } from "react";
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

const CARD_WIDTH = 260;
const CARD_MARGIN = 8;

export function HelperChip({ helper, card, unsatisfiedFriend, friendHighlight, onHoverChange }: Props) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: String(helper.id),
  });
  const [cardPosition, setCardPosition] = useState<{ top: number; left: number } | null>(null);

  const style = transform
    ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`, zIndex: 10 }
    : undefined;

  const highlightClass = friendHighlight ? ` friend-highlight-${friendHighlight}` : "";

  // `position: fixed`, positioned from the chip's own bounding rect, so the
  // card escapes the grid's scrollable-table clipping (overflow-x: auto on
  // an ancestor forces overflow-y: auto too, which would otherwise clip an
  // absolutely-positioned popover) regardless of where in the table the
  // chip sits.
  function handleMouseEnter(event: MouseEvent<HTMLDivElement>) {
    onHoverChange?.(true);
    const rect = event.currentTarget.getBoundingClientRect();
    let left = rect.left;
    if (left + CARD_WIDTH + CARD_MARGIN > window.innerWidth) {
      left = Math.max(CARD_MARGIN, window.innerWidth - CARD_WIDTH - CARD_MARGIN);
    }
    setCardPosition({ top: rect.bottom + 6, left });
  }

  function handleMouseLeave() {
    onHoverChange?.(false);
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
      onMouseLeave={handleMouseLeave}
    >
      {helper.name}
      {helper.can_bring_notebook && <span title="Can bring a notebook"> 💻</span>}
      {helper.can_bring_camera && <span title="Can bring a camera"> 📷</span>}
      {cardPosition && !isDragging && <HelperCard data={card} top={cardPosition.top} left={cardPosition.left} />}
    </div>
  );
}
